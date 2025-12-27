"""
Discord AI Notetaker Bot
Records and transcribes voice channel discussions, then summarizes them using local AI.
"""

import os
import asyncio
import wave
import io
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Optional
from collections import defaultdict

# Set library path for Opus on macOS
if os.path.exists('/opt/homebrew/lib'):
    os.environ.setdefault('DYLD_LIBRARY_PATH', '/opt/homebrew/lib')
    if 'DYLD_LIBRARY_PATH' in os.environ:
        os.environ['DYLD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_LIBRARY_PATH', '')

import discord
from discord.ext import commands

from dotenv import load_dotenv

from summarizer import LocalSummarizer
from note_manager import NoteManager
from voice_transcriber import VoiceTranscriber

# Load environment variables
load_dotenv()

# Parse command line arguments
parser = argparse.ArgumentParser(description='Discord AI Notetaker Bot')
parser.add_argument('--debug', '-d', action='store_true',
                    help='Enable debug mode with verbose logging')
args = parser.parse_args()

# Set up logging
DEBUG_MODE = args.debug or os.getenv('DEBUG', 'false').lower() in ('true', '1', 'yes')
log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(message)s' if DEBUG_MODE else '%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S' if DEBUG_MODE else None
)
logger = logging.getLogger(__name__)

if DEBUG_MODE:
    logger.info("🐛 Debug mode enabled - verbose logging active")

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True  # Required to read command messages (privileged intent)
# intents.members = True  # Not needed for voice recording, commented out

bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3')
WHISPER_MODEL = os.getenv('WHISPER_MODEL', 'medium')  # Options: tiny, base, small, medium, large, large-v2, large-v3

# Initialize components
summarizer = LocalSummarizer(OLLAMA_API_URL, OLLAMA_MODEL)
note_manager = NoteManager()
transcriber = VoiceTranscriber(OLLAMA_API_URL, WHISPER_MODEL)

# Track active voice recording sessions
# Structure: {voice_channel_id: {'voice_client': VoiceClient, 'started_at': datetime, 'transcriptions': [], 'audio_buffers': Dict[user_id, List[bytes]], 'recording_task': Task}}
recording_sessions: Dict[int, Dict] = {}


async def finished_callback(sink: discord.sinks.MP3Sink, channel_id: int, *args):
    """Callback when recording is finished - save audio file."""
    if channel_id not in recording_sessions:
        logger.warning(f'finished_callback called for unknown channel: {channel_id}')
        return

    session = recording_sessions[channel_id]
    audio_file = session.get('audio_file')

    if not audio_file:
        logger.error('No audio_file path in session')
        return

    try:
        # Py-cord's MP3Sink saves audio per user in audio_data dict
        # The audio_data values are AudioData objects with a file attribute
        all_audio_files = []
        
        if hasattr(sink, 'audio_data') and sink.audio_data:
            logger.debug(f'Processing audio_data with {len(sink.audio_data)} users')
            for user_id, audio_data in sink.audio_data.items():
                try:
                    # AudioData has a file attribute that's a file-like object
                    if hasattr(audio_data, 'file') and audio_data.file:
                        audio_data.file.seek(0)
                        audio_bytes = audio_data.file.read()
                        if audio_bytes:
                            all_audio_files.append((user_id, audio_bytes))
                            logger.debug(f'Found audio for user {user_id}: {len(audio_bytes)} bytes')
                except Exception as e:
                    logger.error(f'Error reading audio for user {user_id}: {e}')
        else:
            logger.warning('No audio_data in sink or sink.audio_data is empty')

        if all_audio_files:
            # For now, save the first user's audio (or we could combine with FFmpeg)
            # In a real implementation, you'd want to mix all users' audio
            user_id, audio_data = all_audio_files[0]
            with open(audio_file, 'wb') as f:
                f.write(audio_data)
            logger.info(f'✓ Recording saved to {audio_file} ({len(audio_data)} bytes)')
        else:
            logger.warning(f'No audio files found to save for channel {channel_id}')
    except Exception as e:
        logger.error(f'Error saving audio: {e}', exc_info=True)


def format_transcription_for_summary(transcription: Dict) -> str:
    """Format a transcription entry for inclusion in summary."""
    timestamp = transcription['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
    user_id = transcription['user_id']
    text = transcription['text']

    # Try to get username
    user = bot.get_user(user_id)
    username = user.display_name if user else f"User {user_id}"

    return f"[{timestamp}] {username}: {text}"


# Note: discord.py doesn't have built-in audio receiving
# We'll need to use a workaround or third-party library
# For now, implementing a basic solution that attempts to capture audio


async def summarize_transcriptions(ctx: commands.Context, transcriptions: List[Dict], channel_name: str):
    """Summarize collected transcriptions and save as a note."""
    if not transcriptions:
        await ctx.send("No transcriptions collected to summarize.")
        return

    # Format transcriptions for summarization
    formatted_transcriptions = [format_transcription_for_summary(t) for t in transcriptions]
    conversation_text = '\n'.join(formatted_transcriptions)

    # Generate summary (language will be auto-detected from conversation)
    try:
        logger.info(f'Starting summary generation for {channel_name}...')
        logger.debug(f'Transcription length: {len(conversation_text)} characters')
        await ctx.send("📝 Detecting language and generating summary... This may take a moment.")

        summary = await summarizer.summarize(conversation_text, channel_name, language=None)
        logger.info(f'Summary generated successfully! Length: {len(summary)} characters')
        logger.debug(f'Summary preview: {summary[:100]}...')

        # Save the note (we'll store transcriptions as a list of dicts)
        note = note_manager.save_note(
            channel_id=ctx.channel.id,
            channel_name=channel_name,
            messages=transcriptions,  # Store transcriptions instead of messages
            summary=summary,
            timestamp=datetime.now()
        )
        logger.info(f'Note saved with ID: {note["id"]}')

        # Send summary to channel
        embed = discord.Embed(
            title=f"📝 Summary: {channel_name}",
            description=summary,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Transcriptions", value=len(transcriptions), inline=True)
        embed.add_field(name="Note ID", value=note['id'], inline=True)
        embed.set_footer(text="AI Notetaker Bot")

        await ctx.send(embed=embed)
        logger.info(f'Summary sent to Discord channel #{ctx.channel.name}')

    except Exception as e:
        logger.error(f"Error summarizing transcriptions: {e}")
        await ctx.send(f"❌ Error generating summary: {str(e)}")


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guild(s)')
    if DEBUG_MODE:
        for guild in bot.guilds:
            logger.debug(f'  - {guild.name} (id: {guild.id})')

    # Check if Ollama is accessible
    try:
        await summarizer.check_connection()
        logger.info(f'✓ Connected to Ollama at {OLLAMA_API_URL}')
    except Exception as e:
        logger.warning(f'Could not connect to Ollama: {e}')
        logger.warning('Make sure Ollama is running and the model is installed.')


@bot.event
async def on_voice_state_update(member, before, after):
    """Track voice state updates to map SSRC to users."""
    # When users join/leave voice channels, update SSRC mappings
    for channel_id, session in recording_sessions.items():
        receiver = session.get('receiver')
        if receiver and hasattr(member, 'voice') and member.voice:
            # Try to get SSRC from voice state
            if hasattr(member.voice, 'ssrc'):
                receiver.update_ssrc_mapping(member.id, member.voice.ssrc)


@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages - process commands."""
    # Debug: log all messages
    if DEBUG_MODE and message.content.startswith('!'):
        logger.debug(f'Received command: {message.content} from {message.author} in {message.channel}')

    # Process commands
    await bot.process_commands(message)


@bot.command(name='start', aliases=['listen'])
async def cmd_start(ctx: commands.Context):
    """Start listening to voice channel discussions."""
    logger.debug(f'!start command received from {ctx.author} in {ctx.channel}')

    # Check if user is in a voice channel
    if not ctx.author.voice or not ctx.author.voice.channel:
        logger.debug(f'User {ctx.author} is not in a voice channel')
        await ctx.send("❌ You must be in a voice channel to use this command!")
        return

    logger.debug(f'User {ctx.author} is in voice channel: {ctx.author.voice.channel.name}')

    voice_channel = ctx.author.voice.channel
    voice_channel_id = voice_channel.id

    # Check if already recording
    if voice_channel_id in recording_sessions:
        session = recording_sessions[voice_channel_id]
        started_at = session['started_at']
        transcription_count = len(session['transcriptions'])
        duration = (datetime.now() - started_at).total_seconds()

        await ctx.send(
            f"✅ Already listening in {voice_channel.name}!\n"
            f"Started: {started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Duration: {duration:.0f} seconds\n"
            f"Transcriptions: {transcription_count}\n"
            f"Use `!stop` to finish and generate summary."
        )
        return

    # Connect to voice channel
    try:
        voice_client = await voice_channel.connect()
    except discord.ClientException as e:
        await ctx.send(f"❌ Error connecting to voice channel: {str(e)}")
        return

    # Create audio file for recording
    audio_dir = os.path.join(os.getcwd(), 'recordings')
    os.makedirs(audio_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    audio_filename = os.path.join(audio_dir, f'recording_{voice_channel_id}_{timestamp}.mp3')

    # Start recording using Py-cord's built-in MP3 recording
    try:
        sink = discord.sinks.MP3Sink()
        voice_client.start_recording(
            sink,
            finished_callback,
            voice_channel_id
        )

        session = {
            'voice_client': voice_client,
            'channel_name': voice_channel.name,
            'started_at': datetime.now(),
            'started_by': ctx.author.id,
            'audio_file': audio_filename,
            'sink': sink
        }
        recording_sessions[voice_channel_id] = session

        logger.debug(f'Started MP3 recording to {audio_filename}')

    except AttributeError as e:
        await ctx.send("⚠️ **Recording requires Py-cord.** Install with: `pip install py-cord[voice]`\n"
                      "Then restart the bot.")
        await voice_client.disconnect()
        return
    except Exception as e:
        logger.error(f'Failed to start recording: {e}')
        await voice_client.disconnect()
        await ctx.send(f"❌ Failed to start recording: {str(e)}")
        return

    embed = discord.Embed(
        title="🎙️ Started Listening",
        description=f"Now connected to {voice_channel.name}",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
    embed.add_field(name="Started by", value=ctx.author.mention, inline=True)
    embed.set_footer(text="Use !stop to finish")

    await ctx.send(embed=embed)


@bot.command(name='stop', aliases=['end', 'finish'])
async def cmd_stop(ctx: commands.Context):
    """Stop listening and generate summary of voice transcriptions."""
    logger.debug(f'!stop command received from {ctx.author} in {ctx.channel}')
    logger.debug(f'Active recording sessions: {list(recording_sessions.keys())}')
    
    # Find which voice channel the user is in (or check all active sessions)
    voice_channel_id = None

    if ctx.author.voice and ctx.author.voice.channel:
        voice_channel_id = ctx.author.voice.channel.id
        logger.debug(f'User is in voice channel: {voice_channel_id}')

    # If user is in a voice channel, use that; otherwise check if there's only one active session
    if not voice_channel_id:
        logger.debug('User not in voice channel, checking active sessions...')
        if len(recording_sessions) == 1:
            voice_channel_id = list(recording_sessions.keys())[0]
            logger.debug(f'Using only active session: {voice_channel_id}')
        elif len(recording_sessions) > 1:
            # Show all active sessions and let user know
            sessions_list = []
            for vc_id, session in recording_sessions.items():
                channel = bot.get_channel(vc_id)
                channel_name = channel.name if channel else f"Channel {vc_id}"
                duration = (datetime.now() - session['started_at']).total_seconds()
                sessions_list.append(f"• {channel_name}: {duration:.0f}s")
            
            await ctx.send(
                f"❌ Multiple recording sessions active:\n" + "\n".join(sessions_list) + 
                "\n\nPlease join the voice channel you want to stop, or use `!status` to see details."
            )
            return
        else:
            logger.warning('No active recording sessions found')
            await ctx.send("❌ No active recording session found. Use `!start` to begin recording.")
            return

    if voice_channel_id not in recording_sessions:
        logger.warning(f'Voice channel {voice_channel_id} not in recording_sessions')
        logger.warning(f'Available sessions: {list(recording_sessions.keys())}')
        await ctx.send("❌ Not currently recording in that voice channel. Use `!start` to begin recording, or `!status` to check active sessions.")
        return

    # Get session data
    session = recording_sessions[voice_channel_id]
    voice_client = session['voice_client']
    audio_file = session.get('audio_file')
    started_at = session['started_at']
    channel_name = session['channel_name']

    # Stop recording
    try:
        voice_client.stop_recording()
        # Wait for recording to finish and file to be written
        # MP3Sink callback is async, so we need to wait for it to complete
        logger.debug('Waiting for recording to finish...')
        # Wait longer and check if file exists
        for i in range(10):  # Wait up to 10 seconds
            await asyncio.sleep(1)
            if audio_file and os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
                logger.debug(f'Recording file ready after {i+1} seconds')
                break
        else:
            logger.warning('Recording file not ready after 10 seconds')
    except Exception as e:
        logger.error(f'Error stopping recording: {e}')

    # Disconnect from voice channel (but keep session for transcription)
    await voice_client.disconnect()

    # Show session info
    duration = (datetime.now() - started_at).total_seconds()
    embed = discord.Embed(
        title="🛑 Stopped Recording",
        description=f"Session duration: {duration:.0f} seconds",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )
    await ctx.send(embed=embed)

    # Transcribe the recorded audio file
    # NOTE: We keep the session in memory until transcription completes
    if audio_file and os.path.exists(audio_file):
        file_size = os.path.getsize(audio_file)
        logger.info(f'Starting transcription of {os.path.basename(audio_file)} ({file_size} bytes)')
        
        # Check if file has content
        if file_size == 0:
            logger.error(f'Audio file is empty: {audio_file}')
            await ctx.send("⚠️ Audio file was created but is empty. Please check your microphone settings.")
            return
        
        await ctx.send("📝 Transcribing audio... This may take a moment.")

        try:
            # Read the audio file and transcribe
            with open(audio_file, 'rb') as f:
                audio_data = f.read()
                
            if not audio_data or len(audio_data) < 1000:  # Too small to contain audio
                logger.warning(f'Audio file too small: {len(audio_data)} bytes')
                await ctx.send("⚠️ Audio file appears to be empty or too small.")
                return
                
            audio_buffer = io.BytesIO(audio_data)
            audio_buffer.seek(0)

            # Transcribe the entire recording
            logger.debug(f'Calling transcriber with {len(audio_data)} bytes of audio data')
            logger.info(f'Starting transcription process...')
            
            try:
                logger.info(f'Transcriber model: {transcriber.model_name}')
                logger.info(f'Calling transcribe_audio...')
                transcription_text = await transcriber.transcribe_audio(audio_buffer, 0)  # user_id 0 for combined
                logger.info(f'Transcription returned: {type(transcription_text)}')
                logger.info(f'Transcription is None: {transcription_text is None}')
                logger.info(f'Transcription length: {len(transcription_text) if transcription_text else 0}')
                if transcription_text:
                    logger.info(f'Transcription stripped length: {len(transcription_text.strip())}')
                    logger.info(f'Transcription first 100 chars: {repr(transcription_text[:100])}')
            except Exception as transcribe_error:
                logger.error(f'Error during transcription: {transcribe_error}', exc_info=True)
                await ctx.send(f"❌ Error during transcription: {str(transcribe_error)}")
                return

            # Check transcription result more carefully
            if transcription_text is not None and len(transcription_text.strip()) > 0:
                logger.info(f'✓ Transcription completed! Length: {len(transcription_text)} characters')
                logger.debug(f'Transcription preview: {transcription_text[:150]}...')

                # Format as conversation
                transcription_entry = {
                    'user_id': 0,  # Combined transcription
                    'text': transcription_text,
                    'timestamp': started_at
                }

                # Generate summary
                logger.debug('Proceeding to summary generation...')
                await summarize_transcriptions(ctx, [transcription_entry], channel_name)
            else:
                logger.warning('No speech detected in recording')
                logger.warning(f'Audio file size: {file_size} bytes, but transcription returned: {repr(transcription_text)}')
                logger.warning('This could mean:')
                logger.warning('1. The audio file is corrupted or in wrong format')
                logger.warning('2. Whisper model failed to process the audio')
                logger.warning('3. The audio contains only silence or noise')
                await ctx.send("⚠️ No speech was detected in the recording. The audio file was created but Whisper couldn't detect any speech. Check bot logs for details.")
            
            # Remove session after transcription completes
            if voice_channel_id in recording_sessions:
                del recording_sessions[voice_channel_id]
                logger.debug(f'Removed session for channel {voice_channel_id} after transcription')

        except Exception as e:
            logger.error(f'Error transcribing audio file: {e}', exc_info=True)
            await ctx.send(f"❌ Error transcribing audio: {str(e)}")
            # Remove session even on error
            if voice_channel_id in recording_sessions:
                del recording_sessions[voice_channel_id]
    else:
        await ctx.send("⚠️ No audio file was recorded.")
        # Remove session if no audio file
        if voice_channel_id in recording_sessions:
            del recording_sessions[voice_channel_id]


@bot.command(name='status')
async def cmd_status(ctx: commands.Context):
    """Check if bot is currently recording in a voice channel."""
    voice_channel_id = None

    if ctx.author.voice and ctx.author.voice.channel:
        voice_channel_id = ctx.author.voice.channel.id

    if not voice_channel_id or voice_channel_id not in recording_sessions:
        # Show all active sessions
        if not recording_sessions:
            await ctx.send("❌ No active recording sessions.")
        else:
            sessions_list = []
            for vc_id, session in recording_sessions.items():
                channel = bot.get_channel(vc_id)
                channel_name = channel.name if channel else f"Channel {vc_id}"
                duration = (datetime.now() - session['started_at']).total_seconds()
                sessions_list.append(
                    f"• {channel_name}: {duration:.0f}s, {len(session['transcriptions'])} transcriptions"
                )
            await ctx.send(f"📊 Active sessions:\n" + "\n".join(sessions_list))
        return

    session = recording_sessions[voice_channel_id]
    started_at = session['started_at']
    transcription_count = len(session['transcriptions'])
    duration = (datetime.now() - started_at).total_seconds()
    channel_name = session['channel_name']

    embed = discord.Embed(
        title="🎙️ Recording Status",
        description=f"Currently recording from {channel_name}",
        color=discord.Color.green(),
        timestamp=started_at
    )
    embed.add_field(name="Duration", value=f"{duration:.0f} seconds", inline=True)
    embed.add_field(name="Transcriptions", value=transcription_count, inline=True)
    embed.set_footer(text="Use !stop to finish and generate summary")

    await ctx.send(embed=embed)


@bot.command(name='notes', aliases=['listnotes'])
async def cmd_list_notes(ctx: commands.Context, limit: int = 10):
    """List recent notes."""
    notes = note_manager.get_notes_for_channel(ctx.channel.id, limit=limit)

    if not notes:
        await ctx.send("No notes found.")
        return

    embed = discord.Embed(
        title=f"📚 Recent Notes",
        color=discord.Color.green()
    )

    for note in notes[:5]:  # Show up to 5 in embed
        timestamp = note['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        preview = note['summary'][:100] + '...' if len(note['summary']) > 100 else note['summary']
        embed.add_field(
            name=f"Note #{note['id']} - {timestamp}",
            value=preview,
            inline=False
        )

    if len(notes) > 5:
        embed.set_footer(text=f"Showing 5 of {len(notes)} notes. Use !note <id> to view full note.")

    await ctx.send(embed=embed)


@bot.command(name='note')
async def cmd_get_note(ctx: commands.Context, note_id: int):
    """Get a specific note by ID."""
    note = note_manager.get_note(note_id)

    if not note:
        await ctx.send(f"Note #{note_id} not found.")
        return

    embed = discord.Embed(
        title=f"📝 Note #{note_id}",
        description=note['summary'],
        color=discord.Color.blue(),
        timestamp=note['timestamp']
    )
    embed.add_field(name="Channel", value=note['channel_name'], inline=True)
    embed.add_field(name="Items", value=note['message_count'], inline=True)

    await ctx.send(embed=embed)


@bot.command(name='stats')
async def cmd_stats(ctx: commands.Context):
    """Show bot statistics."""
    total_notes = note_manager.get_total_notes()
    active_sessions = len(recording_sessions)

    embed = discord.Embed(
        title="📊 Bot Statistics",
        color=discord.Color.gold()
    )
    embed.add_field(name="Total Notes", value=total_notes, inline=True)
    embed.add_field(name="Active Recording Sessions", value=active_sessions, inline=True)
    embed.add_field(name="Model", value=OLLAMA_MODEL, inline=True)

    await ctx.send(embed=embed)


@bot.command(name='help_bot')
async def cmd_help(ctx: commands.Context):
    """Show help message."""
    embed = discord.Embed(
        title="🤖 AI Notetaker Bot Commands",
        description="Commands to interact with the notetaker bot",
        color=discord.Color.purple()
    )
    embed.add_field(
        name="!start / !listen",
        value="Start recording from the voice channel you're in",
        inline=False
    )
    embed.add_field(
        name="!stop / !end / !finish",
        value="Stop recording and generate summary of transcriptions",
        inline=False
    )
    embed.add_field(
        name="!status",
        value="Check recording status",
        inline=False
    )
    embed.add_field(
        name="!notes / !listnotes [limit]",
        value="List recent notes (default: 10)",
        inline=False
    )
    embed.add_field(
        name="!note <id>",
        value="View a specific note by ID",
        inline=False
    )
    embed.add_field(
        name="!stats",
        value="Show bot statistics",
        inline=False
    )

    await ctx.send(embed=embed)


def main():
    """Start the bot."""
    if not DISCORD_BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN not found in environment variables!")
        logger.error("Please create a .env file with your bot token.")
        return

    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        logger.error("\n" + "="*60)
        logger.error("ERROR: Privileged Intents Not Enabled!")
        logger.error("="*60)
        logger.error("\nYou need to enable 'MESSAGE CONTENT INTENT' in Discord Developer Portal:")
        logger.error("1. Go to https://discord.com/developers/applications")
        logger.error("2. Select your application")
        logger.error("3. Go to 'Bot' section")
        logger.error("4. Scroll to 'Privileged Gateway Intents'")
        logger.error("5. Enable 'MESSAGE CONTENT INTENT'")
        logger.error("6. Click 'Save Changes'")
        logger.error("\nThen restart the bot.")
        logger.error("="*60 + "\n")
        raise


if __name__ == '__main__':
    main()
