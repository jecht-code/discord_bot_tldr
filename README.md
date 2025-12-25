# Discord Bot TLDR

Quick catch-up summaries for busy people. A Discord bot that summarizes conversations using Claude AI and tracks your reading position with bookmarks.

## Features

- `/tldr [count]` - Summarize the last N messages (default: 50, max: 200)
- `/catchup` - Summarize everything since your last bookmark
- `/mark` - Set bookmark at current position without summarizing
- Powered by Claude 3.5 Sonnet for high-quality summaries
- Personal bookmark tracking per channel
- Clean Discord embeds for output

## Prerequisites

- Python 3.10 or 3.11 (recommended for Windows)
- Discord Bot Token (from Discord Developer Portal)
- Claude API Key (from Anthropic Console)

## Setup Instructions (Windows)

### 1. Check Python Version

```bash
python --version
```

Make sure you have Python 3.10 or 3.11. If you're on 3.12 and encounter issues, install 3.11.

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Or install manually:
```bash
pip install discord.py python-dotenv anthropic
```

### 3. Configure Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to the "Bot" section and create a bot
4. Copy the bot token
5. **Important:** Enable "Message Content Intent" in the Bot settings

### 4. Get Claude API Key

1. Go to [Anthropic Console](https://console.anthropic.com)
2. Sign in or create an account
3. Go to API Keys section
4. Click "Create Key"
5. Name it "Discord Bot TLDR" (or similar)
6. Copy the API key

### 5. Set Up Environment Variables

Copy the `.env.example` file to `.env`:
```bash
copy .env.example .env
```

Edit `.env` and paste both your Discord bot token and Claude API key:
```
DISCORD_TOKEN=your_discord_bot_token_here
ANTHROPIC_API_KEY=your_claude_api_key_here
```

### 6. Invite Bot to Your Server

1. In Discord Developer Portal, go to Installation (left sidebar)
2. Copy the install link
3. Open it in your browser
4. Select your server and authorize
5. Make sure the bot has these permissions:
   - Read Messages/View Channels
   - Send Messages
   - Read Message History

### 7. Run the Bot

```bash
python bot.py
```

When you see `Logged in as YourBot (ready)`, the bot is running!

## Usage

In any text channel where the bot has access:

### Quick Summary
```
/tldr
```
Summarizes the last 50 messages. Add a number for more: `/tldr 100`

### Catch Up Since Last Visit
```
/catchup
```
Summarizes all messages since your last bookmark (or last 50 if first time).

### Mark Your Position
```
/mark
```
Sets your bookmark without generating a summary. Use `/catchup` later to see what you missed.

## How It Works

- **Bookmarks**: Tracks the last message you've summarized per channel using a local SQLite database
- **Summarization**: Uses Claude 3.5 Sonnet API to generate concise TL;DR summaries
- **Text Cleaning**: Removes Discord formatting (mentions, emoji, code blocks) for cleaner summaries
- **Cost**: Approximately $0.001-0.003 per summary (extremely low cost)

## Troubleshooting

### "Missing ANTHROPIC_API_KEY" Error

Make sure you created a `.env` file (not `.env.example`) and added your Claude API key.

### Bot Sees Empty Messages

Make sure "Message Content Intent" is enabled in Discord Developer Portal under Bot settings.

### API Rate Limit Errors

Claude API has generous rate limits. If you hit them, the bot will use a fallback (first 100 chars of each person's messages).

### Import Errors

Make sure you installed all dependencies:
```bash
pip install discord.py python-dotenv anthropic
```

## Project Structure

```
discord_bot_tldr/
├── bot.py              # Main bot code
├── requirements.txt    # Python dependencies
├── .env               # Your Discord token (not in git)
├── .env.example       # Template for .env
├── bookmarks.db       # SQLite database (created on first run)
└── README.md          # This file
```

## Notes

- "Unread" tracking is based on your bookmark, not Discord's native unread state (which isn't exposed to bots)
- `/tldr` supports 5-200 messages, `/catchup` fetches up to 200 messages since bookmark
- Summaries are fast (1-3 seconds) using Claude API
- Each summary costs approximately $0.001-0.003 (very affordable)
- Your Claude API key is stored locally in `.env` (never committed to git)
