# Discord Bot TLDR

A Discord bot that summarizes messages in channels based on user requests. The bot uses local AI (distilbart-cnn) to generate summaries and tracks your reading position with bookmarks.

## Features

- Summarize unread messages in Discord channels
- Personal bookmark tracking (remembers where you left off)
- Local AI summarization (no external API needed)
- Privacy-focused (runs on your machine)

## Prerequisites

- Python 3.10 or 3.11 (recommended for Windows)
- Discord Bot Token (from Discord Developer Portal)

## Setup Instructions (Windows)

### 1. Check Python Version

```bash
python --version
```

Make sure you have Python 3.10 or 3.11. If you're on 3.12 and encounter issues, install 3.11.

### 2. Install Dependencies

The easiest way on Windows is to install PyTorch first, then the rest:

**Install CPU-only PyTorch:**
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

**Install remaining dependencies:**
```bash
pip install discord.py python-dotenv transformers
```

Alternatively, you can use the requirements.txt (but remove the torch line first):
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

### 3. Configure Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to the "Bot" section and create a bot
4. Copy the bot token
5. **Important:** Enable "Message Content Intent" in the Bot settings

### 4. Set Up Environment Variables

Copy the `.env.example` file to `.env`:
```bash
copy .env.example .env
```

Edit `.env` and paste your Discord bot token:
```
DISCORD_TOKEN=your_actual_bot_token_here
SUMMARY_MODEL=sshleifer/distilbart-cnn-12-6
```

### 5. Invite Bot to Your Server

1. In Discord Developer Portal, go to OAuth2 > URL Generator
2. Select scopes: `bot` and `applications.commands`
3. Select bot permissions: `Read Messages/View Channels`, `Send Messages`, `Read Message History`
4. Copy the generated URL and open it in your browser
5. Select your server and authorize the bot

### 6. Run the Bot

```bash
python bot.py
```

On first run, it will download the AI model (one-time, takes a few minutes).

When you see `Logged in as YourBot (ready)`, the bot is running!

## Usage

In any text channel where the bot has access, use:

```
/summary
```

Then choose `last_unread` mode.

The bot will:
- Summarize messages since your last bookmark (or last 50 messages if first time)
- Update your bookmark to the latest message
- Send you a summary

## How It Works

- **Bookmarks**: The bot tracks the last message you've summarized per channel using a local SQLite database
- **Summarization**: Uses distilbart-cnn model running locally on your CPU
- **Privacy**: All data stays on your machine - no external API calls

## Troubleshooting

### "Microsoft Visual C++ Build Tools" Error

The installation steps above should avoid this. If you still get it, make sure you're installing PyTorch from the CPU wheel as shown above.

### Bot Sees Empty Messages

Make sure "Message Content Intent" is enabled in Discord Developer Portal under Bot settings.

### Import Errors

Make sure you installed all dependencies:
```bash
pip install discord.py python-dotenv transformers torch
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
- The bot processes up to 50 messages at a time for performance
- Summaries are generated locally, so quality depends on your CPU (first summary may take a few seconds)

## Future Improvements

- Multiple summary modes (bullet points, detailed, brief)
- Custom message limits
- Better model options
- Multi-channel summaries
