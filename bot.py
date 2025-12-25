import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List

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

# ---- SQLite bookmark store ----
DB_PATH = "bookmarks.db"

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bookmarks (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                last_seen_message_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, user_id)
            )
            """
        )
        con.commit()

def get_bookmark(guild_id: int, channel_id: int, user_id: int) -> Optional[int]:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            """
            SELECT last_seen_message_id
            FROM bookmarks
            WHERE guild_id=? AND channel_id=? AND user_id=?
            """,
            (str(guild_id), str(channel_id), str(user_id)),
        ).fetchone()
    if not row:
        return None
    try:
        return int(row[0])
    except ValueError:
        return None

def set_bookmark(guild_id: int, channel_id: int, user_id: int, message_id: int) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO bookmarks (guild_id, channel_id, user_id, last_seen_message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, user_id)
            DO UPDATE SET last_seen_message_id=excluded.last_seen_message_id, updated_at=excluded.updated_at
            """,
            (
                str(guild_id),
                str(channel_id),
                str(user_id),
                str(message_id),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        con.commit()

# ---- Helpers ----
def clean_text(s: str) -> str:
    # Remove common discord noise
    s = re.sub(r"<@!?(\d+)>", "@user", s)          # mentions
    s = re.sub(r"<#(\d+)>", "#channel", s)         # channel mentions
    s = re.sub(r"<@&(\d+)>", "@role", s)           # role mentions
    s = re.sub(r"https?://\S+", "[link]", s)       # links
    s = s.replace("```", "")                       # code fences
    return s.strip()

def create_participant_summaries(messages: List[discord.Message]) -> str:
    """
    Group messages by participant and create individual summaries using Claude API.
    Returns formatted string with each participant's summary.
    """
    from collections import defaultdict

    # Group messages by author
    participant_messages = defaultdict(list)
    for m in messages:
        author = m.author.display_name
        content = clean_text(m.content)
        if content:
            participant_messages[author].append(content)

    # Build conversation context for Claude
    conversation_lines = []
    for author, msgs in participant_messages.items():
        for msg in msgs:
            conversation_lines.append(f"[{author}] {msg}")

    # Create prompt for Claude
    prompt = f"""You are summarizing a Discord conversation. Below are messages from a chat, grouped by participant.

Your task:
1. For each participant, write a 1-2 sentence summary of what they discussed
2. Format as: **Name:** summary
3. Focus on main topics and key points
4. Keep summaries concise and clear

Messages:
{chr(10).join(conversation_lines)}

Provide per-participant summaries now:"""

    try:
        # Call Claude API
        response = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Extract summary from response
        summary_text = response.content[0].text.strip()
        return summary_text

    except Exception as e:
        # Fallback if API fails
        summaries = []
        for author, msgs in participant_messages.items():
            combined = " ".join(msgs)
            preview = combined[:100] + "..." if len(combined) > 100 else combined
            summaries.append(f"**{author}:** {preview}")
        return "\n".join(summaries)

# ---- Discord bot ----
intents = discord.Intents.default()
intents.message_content = True  # REQUIRED for reading message content
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    init_db()
    # Sync commands to Discord
    await tree.sync()
    print(f"Logged in as {client.user} (ready)")

@tree.command(name="summary", description="Summarize what you missed.")
@app_commands.describe(mode="Choose summary mode")
@app_commands.choices(
    mode=[
        app_commands.Choice(name="last_unread", value="last_unread"),
    ]
)
async def summary(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    if not interaction.guild or not interaction.channel:
        await interaction.response.send_message("This command only works in a server channel.", ephemeral=True)
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("This command works in text channels only.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    guild_id = interaction.guild.id
    channel_id = channel.id
    user_id = interaction.user.id

    # Bookmark logic
    last_seen = get_bookmark(guild_id, channel_id, user_id)

    # Pull messages:
    # - If we have a bookmark: fetch after it
    # - If not: default to last 50 messages
    messages: List[discord.Message] = []
    if last_seen:
        # Fetch messages after bookmark, cap to 50
        async for m in channel.history(limit=200, after=discord.Object(id=last_seen), oldest_first=True):
            if m.author.bot:
                continue
            messages.append(m)
            if len(messages) >= 50:
                break
    else:
        # First run: take last 50 messages (most recent)
        msgs = [m async for m in channel.history(limit=50)]
        # Reverse to chronological order (oldest first) for coherent summary
        msgs.reverse()
        messages = [m for m in msgs if not m.author.bot]

    if not messages:
        await interaction.followup.send("Nothing new to summarize (no messages after your last bookmark).")
        # If we have a bookmark already, keep it. If not, set to current latest message.
        last_msg = await channel.fetch_message(channel.last_message_id) if channel.last_message_id else None
        if last_msg:
            set_bookmark(guild_id, channel_id, user_id, last_msg.id)
        return

    # Create per-participant summaries
    summary_text = create_participant_summaries(messages)
    if not summary_text.strip():
        await interaction.followup.send("Nothing to summarize (messages had no text content).")
        return

    # Update bookmark to the last message we summarized (silently)
    newest_id = messages[-1].id
    set_bookmark(guild_id, channel_id, user_id, newest_id)

    # Post result - clean format with participant summaries
    header = f"**Summary ({len(messages)} messages)**\n"
    await interaction.followup.send(f"{header}{summary_text}")

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
