"""
Discord TL;DR Bot - Quick catch-up summaries for busy people.

Commands:
    /tldr [count]     - Summarize the last N messages (default: 50)
    /catchup          - Summarize everything since your last bookmark
    /mark             - Set bookmark at current position without summarizing
    /topside          - Get ARC Raiders event timers

Uses Claude Sonnet 4 API for high-quality conversational summaries.
"""

import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("Missing ANTHROPIC_API_KEY in .env")

# ---- Claude API client ----
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ---- Metaforge API ----
METAFORGE_EVENT_TIMERS_URL = "https://metaforge.app/api/arc-raiders/event-timers"

# ---- SQLite bookmark store ----
DB_PATH = "bookmarks.db"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                last_seen_message_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, user_id)
            )
        """)
        con.commit()


def get_bookmark(guild_id: int, channel_id: int, user_id: int) -> Optional[int]:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT last_seen_message_id FROM bookmarks WHERE guild_id=? AND channel_id=? AND user_id=?",
            (str(guild_id), str(channel_id), str(user_id)),
        ).fetchone()
    if row:
        try:
            return int(row[0])
        except ValueError:
            pass
    return None


def set_bookmark(guild_id: int, channel_id: int, user_id: int, message_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO bookmarks (guild_id, channel_id, user_id, last_seen_message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, user_id)
            DO UPDATE SET last_seen_message_id=excluded.last_seen_message_id, updated_at=excluded.updated_at
        """, (
            str(guild_id), str(channel_id), str(user_id),
            str(message_id), datetime.now(timezone.utc).isoformat()
        ))
        con.commit()


# ---- Text Processing ----

def clean_message(text: str) -> str:
    """Clean Discord-specific formatting from message text."""
    text = re.sub(r"<@!?(\d+)>", "", text)           # Remove user mentions
    text = re.sub(r"<#(\d+)>", "", text)             # Remove channel mentions
    text = re.sub(r"<@&(\d+)>", "", text)            # Remove role mentions
    text = re.sub(r"<a?:\w+:\d+>", "", text)         # Remove custom emoji
    text = re.sub(r"https?://\S+", "[link]", text)   # Simplify links
    text = re.sub(r"```[\s\S]*?```", "[code]", text) # Simplify code blocks
    text = re.sub(r"`[^`]+`", "[code]", text)        # Simplify inline code
    text = re.sub(r"\s+", " ", text)                 # Normalize whitespace
    return text.strip()


def format_conversation(messages: List[discord.Message]) -> str:
    """
    Format messages as a natural conversation for Claude.

    Format:
        Person A: message
        Person B: reply
        Person A: another message
    """
    lines = []

    for msg in messages:
        content = clean_message(msg.content)
        if not content or len(content) < 2:
            continue

        # Use display name, truncate if too long
        author = msg.author.display_name[:20]
        lines.append(f"{author}: {content}")

    return "\n".join(lines)


def generate_tldr(text: str) -> str:
    """
    Generate a concise TL;DR summary using Claude API.
    """
    if not text or len(text.strip()) < 10:
        return "Not enough content to summarize."

    prompt = f"""You are summarizing a Discord conversation. Create a concise TL;DR summary.

Rules:
1. Be brief - aim for 2-4 sentences max
2. Focus on the main topics and key points
3. Mention who discussed what if relevant
4. Use casual, conversational tone
5. Don't start with "The conversation" or similar - just dive into the summary

Conversation:
{text}

TL;DR:"""

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"Claude API error: {e}")
        return "Error generating summary. Please try again."


# ---- Discord Bot ----

intents = discord.Intents.default()
intents.message_content = True  # Required for reading messages
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    init_db()
    await tree.sync()
    print(f"Logged in as {client.user} (ready)")
    print(f"Commands synced: /tldr, /catchup, /mark, /topside")


@tree.command(name="tldr", description="Get a quick TL;DR of recent messages")
@app_commands.describe(count="Number of messages to summarize (default: 50, max: 200)")
async def tldr_command(interaction: discord.Interaction, count: int = 50):
    """Summarize the last N messages in the channel."""

    if not interaction.guild or not interaction.channel:
        await interaction.response.send_message(
            "This command only works in server channels.", ephemeral=True
        )
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "This command only works in text channels.", ephemeral=True
        )
        return

    # Validate count
    count = max(5, min(count, 200))  # Clamp between 5-200

    await interaction.response.defer(thinking=True)

    # Fetch messages
    messages: List[discord.Message] = []
    async for msg in channel.history(limit=count * 2):  # Fetch extra to filter bots
        if msg.author.bot:
            continue
        messages.append(msg)
        if len(messages) >= count:
            break

    # Reverse to chronological order (oldest first)
    messages.reverse()

    if not messages:
        await interaction.followup.send("No messages found to summarize.")
        return

    # Generate summary
    conversation = format_conversation(messages)
    if len(conversation.strip()) < 20:
        await interaction.followup.send("Not enough text content to summarize.")
        return

    summary = generate_tldr(conversation)

    # Update bookmark to most recent message
    set_bookmark(
        interaction.guild.id,
        channel.id,
        interaction.user.id,
        messages[-1].id
    )

    # Send clean embed
    embed = discord.Embed(
        title="TL;DR",
        description=summary,
        color=discord.Color.green()
    )
    embed.set_footer(text=f"{len(messages)} messages | Bookmark updated")

    await interaction.followup.send(embed=embed)


@tree.command(name="catchup", description="Summarize everything since your last visit")
async def catchup_command(interaction: discord.Interaction):
    """Summarize all messages since the user's last bookmark."""

    if not interaction.guild or not interaction.channel:
        await interaction.response.send_message(
            "This command only works in server channels.", ephemeral=True
        )
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "This command only works in text channels.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    guild_id = interaction.guild.id
    channel_id = channel.id
    user_id = interaction.user.id

    # Get user's bookmark
    last_seen = get_bookmark(guild_id, channel_id, user_id)

    messages: List[discord.Message] = []

    if last_seen:
        # Fetch messages after bookmark
        async for msg in channel.history(limit=200, after=discord.Object(id=last_seen), oldest_first=True):
            if msg.author.bot:
                continue
            messages.append(msg)
    else:
        # No bookmark - use last 50 messages
        msgs = [m async for m in channel.history(limit=50)]
        msgs.reverse()
        messages = [m for m in msgs if not m.author.bot]

    if not messages:
        await interaction.followup.send(
            "You're all caught up! No new messages since your last bookmark."
        )
        return

    # Generate summary
    conversation = format_conversation(messages)
    if len(conversation.strip()) < 20:
        await interaction.followup.send("Not enough text content to summarize.")
        return

    summary = generate_tldr(conversation)

    # Update bookmark
    set_bookmark(guild_id, channel_id, user_id, messages[-1].id)

    # Send embed
    embed = discord.Embed(
        title="Catch-Up Summary",
        description=summary,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"{len(messages)} new messages | Bookmark updated")

    await interaction.followup.send(embed=embed)


@tree.command(name="mark", description="Set your bookmark to the current position")
async def mark_command(interaction: discord.Interaction):
    """Set bookmark without generating a summary."""

    if not interaction.guild or not interaction.channel:
        await interaction.response.send_message(
            "This command only works in server channels.", ephemeral=True
        )
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "This command only works in text channels.", ephemeral=True
        )
        return

    # Get the most recent message
    last_msg = None
    async for msg in channel.history(limit=1):
        last_msg = msg
        break

    if not last_msg:
        await interaction.response.send_message(
            "No messages found in this channel.", ephemeral=True
        )
        return

    set_bookmark(
        interaction.guild.id,
        channel.id,
        interaction.user.id,
        last_msg.id
    )

    await interaction.response.send_message(
        "Bookmark set! Use `/catchup` next time to see what you missed.",
        ephemeral=True
    )


@tree.command(name="topside", description="Get ARC Raiders event timers from Metaforge")
async def topside_command(interaction: discord.Interaction):
    """Fetch and display ARC Raiders event timers."""

    await interaction.response.defer(thinking=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(METAFORGE_EVENT_TIMERS_URL) as response:
                if response.status != 200:
                    await interaction.followup.send(
                        f"Failed to fetch event timers (HTTP {response.status})"
                    )
                    return
                data = await response.json()
    except Exception as e:
        print(f"Metaforge API error: {e}")
        await interaction.followup.send("Error connecting to Metaforge API.")
        return

    events = data.get("data", [])
    if not events:
        await interaction.followup.send("No events found.")
        return

    # Get current UTC time for comparison (API times are in UTC)
    now_utc = datetime.now(timezone.utc)
    current_hour = now_utc.hour
    current_minute = now_utc.minute

    # Convert to Eastern time for display
    eastern = ZoneInfo("America/New_York")
    now_eastern = now_utc.astimezone(eastern)

    # Group events by map for better organization
    events_by_map: dict[str, list] = {}
    for event in events:
        map_name = event.get("map", "Unknown")
        if map_name not in events_by_map:
            events_by_map[map_name] = []
        events_by_map[map_name].append(event)

    # Create embeds (Discord limits to 10 embeds per message)
    embeds = []

    # Main header embed
    header_embed = discord.Embed(
        title="ARC Raiders - Topside Event Timers",
        description=f"Current time: **{now_eastern.strftime('%I:%M %p')} ET**\nAll event times shown in UTC (24h format)",
        color=discord.Color.orange()
    )
    header_embed.set_footer(text="Data from metaforge.app")
    embeds.append(header_embed)

    # Create an embed for each map
    for map_name, map_events in sorted(events_by_map.items()):
        map_embed = discord.Embed(
            title=f"{map_name}",
            color=discord.Color.dark_orange()
        )

        for event in map_events:
            event_name = event.get("name", "Unknown Event")
            times = event.get("times", [])

            if not times:
                continue

            # Format time windows
            time_strings = []
            is_active = False

            for t in times:
                start = t.get("start", "??:??")
                end = t.get("end", "??:??")

                # Check if currently active
                try:
                    start_hour = int(start.split(":")[0])
                    end_hour = int(end.split(":")[0])

                    # Handle midnight wrap (e.g., 22:00 - 00:00)
                    if end_hour == 0:
                        end_hour = 24

                    if start_hour <= current_hour < end_hour:
                        time_strings.append(f"**{start} - {end}** (ACTIVE)")
                        is_active = True
                    else:
                        time_strings.append(f"{start} - {end}")
                except:
                    time_strings.append(f"{start} - {end}")

            # Add field for this event
            status_icon = "🟢" if is_active else "⏰"
            field_value = "\n".join(time_strings) if time_strings else "No times listed"

            map_embed.add_field(
                name=f"{status_icon} {event_name}",
                value=field_value,
                inline=True
            )

        # Only add embed if it has events
        if map_embed.fields:
            embeds.append(map_embed)

    # Discord limits to 10 embeds per message
    await interaction.followup.send(embeds=embeds[:10])


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
