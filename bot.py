import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List

import discord
from discord import app_commands
from dotenv import load_dotenv

from transformers import pipeline

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MODEL_NAME = os.getenv("SUMMARY_MODEL", "sshleifer/distilbart-cnn-12-6")

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")

# ---- Summarizer (local CPU) ----
# This loads once at startup. First run may take a bit to download the model.
summarizer = pipeline("summarization", model=MODEL_NAME, device=-1)

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

def format_messages_for_summary(messages: List[discord.Message]) -> str:
    # Keep it compact and consistent for the summarizer
    lines = []
    for m in messages:
        author = m.author.display_name
        content = clean_text(m.content)
        if not content:
            continue
        lines.append(f"{author}: {content}")
    return "\n".join(lines)

def summarize_text(text: str) -> str:
    """
    distilbart-cnn has input limits. We'll:
    - chunk by characters (simple, reliable)
    - summarize each chunk
    - then summarize the summaries (optional)
    """
    if not text:
        return "No text to summarize."

    # Rough safe chunk size for this model
    CHUNK_CHARS = 2500
    chunks = [text[i:i+CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]

    partial_summaries = []
    for ch in chunks:
        # Adjust lengths to avoid weird outputs
        out = summarizer(ch, max_length=130, min_length=40, do_sample=False)
        partial_summaries.append(out[0]["summary_text"].strip())

    if len(partial_summaries) == 1:
        return partial_summaries[0]

    combined = " ".join(partial_summaries)
    final = summarizer(combined, max_length=140, min_length=50, do_sample=False)[0]["summary_text"].strip()
    return final

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
        # First run: take last 50 messages (oldest_first for coherent summary)
        msgs = [m async for m in channel.history(limit=50, oldest_first=True)]
        messages = [m for m in msgs if not m.author.bot]

    if not messages:
        await interaction.followup.send("Nothing new to summarize (no messages after your last bookmark).")
        # If we have a bookmark already, keep it. If not, set to current latest message.
        last_msg = await channel.fetch_message(channel.last_message_id) if channel.last_message_id else None
        if last_msg:
            set_bookmark(guild_id, channel_id, user_id, last_msg.id)
        return

    # Create the input text
    source_text = format_messages_for_summary(messages)
    if not source_text.strip():
        await interaction.followup.send("Nothing to summarize (messages had no text content).")
        return

    # Summarize locally
    summary_text = summarize_text(source_text)

    # Update bookmark to the last message we summarized
    newest_id = messages[-1].id
    set_bookmark(guild_id, channel_id, user_id, newest_id)

    # Post result (kept short-ish for Discord)
    header = f"**Summary (last unread · up to {len(messages)} messages)**"
    footer = f"_Bookmark updated to message ID {newest_id}._"
    await interaction.followup.send(f"{header}\n{summary_text}\n\n{footer}")

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
