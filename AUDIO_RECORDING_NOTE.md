# Audio Recording Implementation Note

## Current Status

The bot can connect to voice channels, but **audio recording is not yet fully implemented** because:

1. `discord.py` doesn't have built-in audio receiving capabilities
2. The `discord.sinks` module doesn't exist in current versions
3. Receiving audio requires implementing RTP/Opus protocol decoding

## What Works Now

- ✅ Bot connects to voice channels
- ✅ Bot tracks recording sessions
- ✅ Bot can disconnect from voice channels
- ❌ Audio recording/transcription (needs implementation)

## Implementation Options

### Option 1: Use discord-recorder library
```bash
pip install discord-recorder
```
This library provides audio recording functionality for discord.py bots.

### Option 2: Implement RTP/Opus decoding
This requires:
- Parsing RTP packets from voice websocket
- Decoding Opus audio to PCM
- Buffering audio per user
- Converting to WAV format for Whisper

This is complex and requires low-level protocol implementation.

### Option 3: Use external recording
Record audio at the system level (e.g., using `ffmpeg` to capture Discord's audio output), then process the files.

## Recommended Next Steps

1. **Short-term**: Use the bot for session tracking (it can join/leave channels)
2. **Medium-term**: Integrate `discord-recorder` or similar library
3. **Long-term**: Implement custom RTP/Opus decoder if needed

## Current Workaround

For now, the bot will:
- Join voice channels when you use `!start`
- Track the session duration
- Disconnect when you use `!stop`
- Show a message that recording isn't fully implemented yet

To actually record and transcribe, we need to implement one of the options above.

