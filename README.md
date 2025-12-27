# Discord AI Notetaker Bot

An intelligent Discord bot that records and transcribes voice channel discussions, then summarizes them using local AI (Ollama). No external API calls needed - everything runs locally on your machine.

## Features

- 🎙️ **Voice Channel Recording**: Records audio from Discord voice channels
- 📝 **Speech-to-Text**: Transcribes voice discussions to text using Whisper
- 🤖 **AI Summarization**: Automatically generates summaries from transcriptions
- 📚 **Note Management**: Store and retrieve summaries with easy commands
- 🔒 **Privacy-First**: All processing happens locally - no data sent to external services

## Prerequisites

1. **Python 3.8+**
2. **Ollama** installed and running locally
   - Download from: https://ollama.ai
   - Install model: `ollama pull llama3` (for summarization)
3. **Whisper** for speech-to-text transcription
   - Will be installed via pip: `pip install openai-whisper`
4. **FFmpeg** (required for audio processing)
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt-get install ffmpeg`
   - Windows: Download from https://ffmpeg.org

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create Discord Bot

1. Go to https://discord.com/developers/applications
2. Create a new application (click "New Application" and give it a name)
3. Go to the "Bot" section in the left sidebar
4. Click "Add Bot" or "Reset Token" if bot already exists
5. **Copy the bot token** (this is a SECRET token, NOT a public key - keep it private!)
   - Click "Reset Token" if you need to see it again
   - ⚠️ **Never share this token publicly or commit it to git**
6. **IMPORTANT: Enable Privileged Intents**
   - Scroll down to "Privileged Gateway Intents"
   - Enable "MESSAGE CONTENT INTENT" (required for the bot to read commands)
   - Click "Save Changes"
   - ⚠️ **You MUST enable this or the bot will not work!**
7. **Invite the bot to your server:**
   - Go to "OAuth2" > "URL Generator"
   - Select scopes: ✅ `bot` and ✅ `applications.commands`
   - Select bot permissions:
     - ✅ **Read Messages** (Text Permissions)
     - ✅ **Send Messages** (Text Permissions)
     - ✅ **Embed Links** (Text Permissions)
     - ✅ **Connect** (Voice Permissions)
     - ✅ **Speak** (Voice Permissions)
     - ✅ **Use Voice Activity** (Voice Permissions)
   - Copy the generated URL and open it in your browser
   - Select your server and click "Authorize"
   - ⚠️ **The bot will show as offline until you start it!**

   See `INVITE_BOT.md` for detailed step-by-step instructions.

### 3. Configure Environment

Create a `.env` file in the project root:

```bash
# Discord Bot Token (from Discord Developer Portal > Your App > Bot section)
# This is a SECRET token - keep it private and never share it!
DISCORD_BOT_TOKEN=your_bot_token_here

# Ollama Configuration
OLLAMA_API_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

### 4. Start Ollama

Make sure Ollama is running:

```bash
# Start Ollama service (usually runs automatically)
ollama serve

# Pull model if you haven't already
ollama pull llama3
```

### 5. Run the Bot

```bash
# Normal mode (minimal logging)
python bot.py

# Debug mode (verbose logging)
python bot.py --debug
# or
python bot.py -d

# Or set environment variable
DEBUG=true python bot.py
```

## Commands

- `!start` or `!listen` - Start recording from the voice channel you're in
- `!stop` or `!end` or `!finish` - Stop recording and generate summary of transcriptions
- `!status` - Check recording status
- `!notes [limit]` or `!listnotes [limit]` - List recent notes for the channel (default: 10)
- `!note <id>` - View a specific note by ID
- `!stats` - Show bot statistics
- `!help_bot` - Show help message

## How It Works

1. **Join Voice Channel**: Join a Discord voice channel
2. **Start Recording**: Use `!start` command in any text channel (bot will record from your voice channel)
3. **Voice Recording**: Bot connects to the voice channel and records all audio
4. **Speech-to-Text**: Audio is transcribed to text using Whisper (via Ollama or local installation)
5. **Stop Recording**: Use `!stop` command to finish recording
6. **Automatic Summarization**: When you stop, the bot automatically generates a summary from transcriptions
7. **Local Processing**: All transcription and summarization happens locally
8. **Storage**: Notes are saved locally in JSON format in the `notes/` directory
9. **Display**: Summary is posted to the text channel and saved for later retrieval

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | Required | Your Discord bot token |
| `OLLAMA_API_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3` | Model name to use for summarization |
| `WHISPER_MODEL` | `medium` | Whisper model for transcription (see below) |

### Whisper Model Selection

Whisper models vary in size, speed, and accuracy:

| Model | Size | Speed | Accuracy | Recommended For |
|-------|------|-------|----------|----------------|
| `tiny` | ~39M | Fastest | Basic | Low-end devices |
| `base` | ~74M | Fast | Good | Quick transcriptions |
| `small` | ~244M | Medium | Better | Balanced use |
| `medium` | ~769M | Moderate | **Very Good** | **Recommended default** |
| `large-v3` | ~1550M | Slower | **Best** | **M1/M2 Macs with 16GB+ RAM** |

**For MacBook M1 with 32GB RAM**, we recommend:
- **`large-v3`** for best accuracy (may take longer but worth it)
- **`medium`** for good balance of speed and accuracy (current default)

Set in `.env`: `WHISPER_MODEL=large-v3`

## Recommended Models

- **llama3** - Good balance of quality and speed
- **mistral** - Fast and efficient
- **llama2** - Older but still effective
- **codellama** - If you want better code understanding

Pull a model with: `ollama pull <model_name>`

## Notes Storage

Notes are stored in `notes/notes.json` in JSON format. Each note contains:
- Note ID
- Channel information
- Message count
- Summary text
- Timestamp

## Troubleshooting

### Bot doesn't respond
- Check that the bot token is correct in `.env`
- Verify the bot has proper permissions in your Discord server
- Ensure "Message Content Intent" is enabled

### Summarization fails
- Make sure Ollama is running: `ollama serve`
- Verify the model is installed: `ollama list`
- Check the model name matches in `.env`
- Test Ollama API: `curl http://localhost:11434/api/tags`

### Bot not recording voice
- Make sure you're in a voice channel when using `!start`
- Verify bot has "Connect" and "Speak" permissions in the voice channel
- Check that FFmpeg is installed and accessible
- Use `!status` to check if bot is recording
- Make sure Whisper is available (either via Ollama or local installation)

### Transcription not working
- Make sure `pip install openai-whisper` was run (included in requirements.txt)
- Check that audio is being recorded (bot should be connected to voice channel)
- First transcription may take longer as Whisper downloads the model (~150MB for "base" model)
- Make sure FFmpeg is installed and accessible

## Privacy & Security

- All AI processing happens locally via Ollama
- No data is sent to external services
- Notes are stored locally on your machine
- Discord messages are only processed when the bot is running

## License

MIT License - feel free to modify and use as needed!

