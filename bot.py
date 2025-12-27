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

# Create logs directory if it doesn't exist
logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Create log filename with timestamp
log_filename = datetime.now().strftime('bot_%Y%m%d_%H%M%S.log')
log_filepath = os.path.join(logs_dir, log_filename)

# Configure logging with both file and console handlers
log_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
date_format = '%Y-%m-%d %H:%M:%S'

# Create formatters
file_formatter = logging.Formatter(log_format, datefmt=date_format)
console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s' if DEBUG_MODE else '%(message)s', 
                                     datefmt=date_format if DEBUG_MODE else None)

# File handler - logs everything to file
file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
file_handler.setLevel(log_level)
file_handler.setFormatter(file_formatter)

# Console handler - logs to console
console_handler = logging.StreamHandler()
console_handler.setLevel(log_level)
console_handler.setFormatter(console_formatter)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(log_level)
# Clear any existing handlers to avoid duplicates
root_logger.handlers.clear()
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Suppress noisy discord.opus warnings (corrupted stream errors are normal)
logging.getLogger('discord.opus').setLevel(logging.WARNING)
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.http').setLevel(logging.WARNING)

# Get logger for this module
logger = logging.getLogger(__name__)
logger.info(f'📝 Logging to file: {log_filepath}')

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
            # Save audio files for each user separately
            user_audio_files = {}
            audio_dir = os.path.dirname(audio_file)
            
            for user_id, audio_data in all_audio_files:
                # Create separate file for each user
                user_audio_file = os.path.join(audio_dir, f'user_{user_id}_{os.path.basename(audio_file)}')
                with open(user_audio_file, 'wb') as f:
                    f.write(audio_data)
                user_audio_files[user_id] = user_audio_file
                logger.info(f'✓ Saved audio for user {user_id}: {user_audio_file} ({len(audio_data)} bytes)')
            
            # Store user audio files in session
            session['user_audio_files'] = user_audio_files
            
            # Also save combined audio (for backward compatibility)
            # Use the first user's audio as the combined file
            if all_audio_files:
                user_id, audio_data = all_audio_files[0]
                with open(audio_file, 'wb') as f:
                    f.write(audio_data)
                logger.info(f'✓ Combined recording saved to {audio_file} ({len(audio_data)} bytes)')
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
    username = f"User {user_id}"  # Default fallback
    user = bot.get_user(user_id)
    if user:
        username = user.display_name or user.name or f"User {user_id}"

    return f"[{timestamp}] {username}: {text}"


# Note: discord.py doesn't have built-in audio receiving
# We'll need to use a workaround or third-party library
# For now, implementing a basic solution that attempts to capture audio


async def display_person_summaries(ctx: commands.Context, user_summaries: Dict[int, Dict], channel_name: str, started_at: datetime):
    """Display individual summaries for each person with their tasks and contributions."""
    if not user_summaries:
        return
    
    # Create main embed with overview
    main_embed = discord.Embed(
        title=f"📋 Meeting Summary: {channel_name}",
        description=f"Individual summaries for {len(user_summaries)} participant(s)",
        color=discord.Color.blue(),
        timestamp=started_at
    )
    
    # Add field for each person
    for user_id, data in user_summaries.items():
        username = data['username']
        summary = data['summary']
        
        # Truncate if too long for embed field
        if len(summary) > 1024:
            summary = summary[:1021] + "..."
        
        main_embed.add_field(
            name=f"👤 {username}",
            value=summary,
            inline=False
        )
    
    main_embed.set_footer(text="AI Notetaker Bot - Per-Person Analysis")
    await ctx.send(embed=main_embed)
    
    # If there are many participants, send individual embeds too for better readability
    if len(user_summaries) > 1:
        for user_id, data in user_summaries.items():
            username = data['username']
            summary = data['summary']
            
            person_embed = discord.Embed(
                title=f"📝 {username}'s Contributions & Tasks",
                description=summary,
                color=discord.Color.green(),
                timestamp=started_at
            )
            person_embed.set_footer(text=f"Channel: {channel_name}")
            await ctx.send(embed=person_embed)


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
        # Check if already connected to this channel
        if ctx.guild.voice_client and ctx.guild.voice_client.channel == voice_channel:
            voice_client = ctx.guild.voice_client
            logger.info('Already connected to this voice channel')
        else:
            # Disconnect from any other channel first
            if ctx.guild.voice_client:
                try:
                    await ctx.guild.voice_client.disconnect(force=True)
                    await asyncio.sleep(0.5)  # Brief wait for disconnect to complete
                except:
                    pass  # Ignore disconnect errors
            voice_client = await voice_channel.connect(timeout=10.0, reconnect=False)
    except asyncio.TimeoutError:
        logger.error('Voice connection timeout')
        # Don't send error - just log it
        return
    except discord.ClientException as e:
        logger.error(f'Error connecting to voice: {e}')
        # Don't send error - just log it
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
    logger.info(f'!stop command received from {ctx.author} in {ctx.channel}')
    logger.info(f'Active recording sessions: {list(recording_sessions.keys())}')
    logger.info(f'Recording sessions details: {[(vc_id, s.get("channel_name", "Unknown")) for vc_id, s in recording_sessions.items()]}')
    
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

    # BEFORE checking if session exists, try to find it by guild/voice client matching
    # This prevents false error messages when the session exists but channel ID doesn't match exactly
    if voice_channel_id not in recording_sessions:
        logger.warning(f'Voice channel {voice_channel_id} not in recording_sessions')
        logger.warning(f'Available sessions: {list(recording_sessions.keys())}')
        
        # Try to find session by checking which voice channel the bot is actually connected to
        # The bot might be connected to a different channel ID than what we're checking
        found_session = False
        
        # First, check if there's only one session in this guild - if so, use it
        if ctx.guild:
            guild_sessions = [(vc_id, s) for vc_id, s in recording_sessions.items() 
                            if s.get('voice_client') and s['voice_client'].guild.id == ctx.guild.id]
            if len(guild_sessions) == 1:
                vc_id, session = guild_sessions[0]
                logger.info(f'Found session - only one active in this guild: {vc_id}')
                voice_channel_id = vc_id
                found_session = True
            else:
                # Try to match by user's voice channel
                if ctx.author.voice and ctx.author.voice.channel:
                    for vc_id, session in guild_sessions:
                        if ctx.author.voice.channel.id == vc_id:
                            logger.info(f'Found session by user voice channel match: {vc_id}')
                            voice_channel_id = vc_id
                            found_session = True
                            break
        
        # Don't send error yet - we'll do a final check below after all lookup attempts

    # Final check - if we still don't have a session, check one more time with better logic
    if voice_channel_id not in recording_sessions:
        logger.warning(f'FINAL CHECK: voice_channel_id {voice_channel_id} not in recording_sessions')
        logger.warning(f'Available sessions: {list(recording_sessions.keys())}')
        
        # LAST RESORT: If there's ANY session in this guild, use it
        if ctx.guild and recording_sessions:
            for vc_id, sess in recording_sessions.items():
                if sess.get('voice_client') and sess['voice_client'].guild.id == ctx.guild.id:
                    logger.info(f'LAST RESORT: Using session {vc_id} from same guild')
                    voice_channel_id = vc_id
                    break
        
        # Only return if we STILL don't have a session - RETURN IMMEDIATELY, NO MESSAGES
        if voice_channel_id not in recording_sessions:
            logger.error(f'CRITICAL: Could not find ANY recording session after all lookup attempts')
            logger.error(f'Requested channel: {voice_channel_id}')
            logger.error(f'Available sessions: {list(recording_sessions.keys())}')
            logger.error(f'Guild ID: {ctx.guild.id if ctx.guild else "None"}')
            # RETURN IMMEDIATELY - DO NOT SEND ANY MESSAGE TO DISCORD
            # ABSOLUTELY NO ctx.send() CALLS HERE - JUST RETURN
            return
    
    # Get session data - save critical info before session might be lost
    session = recording_sessions[voice_channel_id]
    voice_client = session['voice_client']
    audio_file = session.get('audio_file')
    started_at = session.get('started_at', datetime.now())
    channel_name = session.get('channel_name', 'Unknown Channel')
    
    # Save these values in case session gets deleted
    saved_audio_file = audio_file
    saved_started_at = started_at
    saved_channel_name = channel_name

    # Stop recording
    try:
        logger.info(f'Stopping recording for channel {voice_channel_id}')
        logger.info(f'Session exists: {voice_channel_id in recording_sessions}')
        logger.info(f'Audio file path: {audio_file}')
        
        # Make sure session stays in memory - don't delete it yet!
        if voice_channel_id not in recording_sessions:
            logger.error(f'CRITICAL: Session deleted before stop_recording!')
            await ctx.send("❌ Session was lost. Please try !start again.")
            return
        
        voice_client.stop_recording()
        logger.info('stop_recording() called, waiting for callback...')
        
        # Wait for recording to finish and file to be written
        # MP3Sink callback is async, so we need to wait for it to complete
        logger.debug('Waiting for recording to finish...')
        # Wait longer and check if file exists and user_audio_files are ready
        for i in range(15):  # Wait up to 15 seconds (increased from 10)
            await asyncio.sleep(1)
            
            # Re-check session still exists
            if voice_channel_id not in recording_sessions:
                logger.error(f'CRITICAL: Session deleted during wait! Iteration {i+1}')
                # Try to continue anyway if we have the audio file path
                if audio_file and os.path.exists(audio_file):
                    logger.warning('Session lost but audio file exists, continuing...')
                    break
                else:
                    await ctx.send("❌ Recording session was lost. Please try again.")
                    return
            
            session = recording_sessions[voice_channel_id]  # Refresh session reference
            
            # Check both combined file and user files
            file_ready = audio_file and os.path.exists(audio_file) and os.path.getsize(audio_file) > 0
            user_files_ready = 'user_audio_files' in session and session.get('user_audio_files', {})
            
            if file_ready:
                logger.info(f'Recording file ready after {i+1} seconds ({os.path.getsize(audio_file)} bytes)')
                if user_files_ready:
                    logger.info(f'User audio files also ready: {len(session["user_audio_files"])} users')
                break
        else:
            logger.warning('Recording file not ready after 15 seconds')
            # Check if we at least have the combined file
            if audio_file and os.path.exists(audio_file):
                file_size = os.path.getsize(audio_file)
                logger.info(f'Combined audio file exists ({file_size} bytes), will use it as fallback')
            else:
                logger.error(f'Audio file does not exist: {audio_file}')
                await ctx.send("⚠️ Recording file was not created. Please check bot logs.")
                if voice_channel_id in recording_sessions:
                    del recording_sessions[voice_channel_id]
                return
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

    # Transcribe the recorded audio files (per-user if available)
    # NOTE: We keep the session in memory until transcription completes
    
    # Re-check session exists (it might have been lost)
    if voice_channel_id not in recording_sessions:
        logger.warning(f'Session lost before transcription, using saved audio file: {saved_audio_file}')
        # Use saved values
        audio_file = saved_audio_file
        started_at = saved_started_at
        channel_name = saved_channel_name
        user_audio_files = {}
    else:
        session = recording_sessions[voice_channel_id]
        # Wait a bit more for callback to complete and set user_audio_files
        await asyncio.sleep(2)
        user_audio_files = session.get('user_audio_files', {})
        audio_file = session.get('audio_file', saved_audio_file)
        started_at = session.get('started_at', saved_started_at)
        channel_name = session.get('channel_name', saved_channel_name)
    
    logger.info(f'Checking for user audio files: {len(user_audio_files)} found')
    logger.debug(f'User audio files: {list(user_audio_files.keys()) if user_audio_files else "None"}')
    logger.debug(f'Session keys: {list(session.keys())}')
    
    if user_audio_files:
        # Transcribe each user separately
        await ctx.send(f"📝 Transcribing audio for {len(user_audio_files)} participant(s)... This may take a moment.")
        
        user_transcriptions = {}
        user_summaries = {}
        
        try:
            for user_id, user_audio_path in user_audio_files.items():
                if not os.path.exists(user_audio_path):
                    logger.warning(f'User audio file not found: {user_audio_path}')
                    continue
                
                file_size = os.path.getsize(user_audio_path)
                if file_size < 1000:
                    logger.warning(f'User {user_id} audio file too small: {file_size} bytes')
                    continue
                
                # Get user name - try multiple methods
                username = f"User {user_id}"  # Default fallback
                
                # Try to get from guild members first (most reliable)
                if ctx.guild:
                    try:
                        member = ctx.guild.get_member(user_id)
                        if not member:
                            # Try fetching if not in cache
                            try:
                                member = await ctx.guild.fetch_member(user_id)
                            except Exception as fetch_error:
                                logger.debug(f'Could not fetch member {user_id}: {fetch_error}')
                        if member:
                            username = member.display_name or member.name
                            logger.info(f'✓ Got username from guild member: {username} (was: User {user_id})')
                    except Exception as e:
                        logger.debug(f'Error getting member from guild: {e}')
                
                # Fallback to bot's user cache
                if username == f"User {user_id}":
                    user = bot.get_user(user_id)
                    if user:
                        username = user.display_name or user.name
                        logger.debug(f'Got username from bot cache: {username}')
                
                # If still not found, try fetching from voice channel
                if username == f"User {user_id}" and voice_channel_id:
                    try:
                        voice_channel = bot.get_channel(voice_channel_id)
                        if voice_channel and hasattr(voice_channel, 'members'):
                            for member in voice_channel.members:
                                if member.id == user_id:
                                    username = member.display_name or member.name
                                    logger.debug(f'Got username from voice channel: {username}')
                                    break
                    except Exception as e:
                        logger.debug(f'Could not fetch from voice channel: {e}')
                
                logger.info(f'Transcribing audio for {username} (user_id: {user_id})')
                
                try:
                    # Read and transcribe user's audio
                    with open(user_audio_path, 'rb') as f:
                        audio_data = f.read()
                    
                    audio_buffer = io.BytesIO(audio_data)
                    audio_buffer.seek(0)
                    
                    transcription_text = await transcriber.transcribe_audio(audio_buffer, user_id)
                    
                    logger.info(f'Transcription for {username}: type={type(transcription_text)}, value={repr(transcription_text[:100]) if transcription_text else None}, length={len(transcription_text) if transcription_text else 0}')
                    
                    if transcription_text and transcription_text.strip():
                        user_transcriptions[user_id] = {
                            'user_id': user_id,
                            'username': username,
                            'text': transcription_text,
                            'timestamp': started_at
                        }
                        logger.info(f'✓ Transcribed {username}: {len(transcription_text)} characters')
                        logger.info(f'Transcription preview: {transcription_text[:200]}')
                    else:
                        logger.error(f'❌ Transcription failed for {username}!')
                        logger.error(f'  - Audio file: {user_audio_path} ({file_size} bytes)')
                        logger.error(f'  - Transcription result: {repr(transcription_text)}')
                        logger.error(f'  - This might be a Whisper issue - audio exists but no text detected')
                        # DON'T skip - try to use it anyway if it's not None
                        if transcription_text is not None:  # Even if empty string, try to use it
                            logger.warning(f'Using empty transcription for {username} (might contain non-printable characters)')
                            user_transcriptions[user_id] = {
                                'user_id': user_id,
                                'username': username,
                                'text': transcription_text,  # Use it even if empty
                                'timestamp': started_at
                            }
                        
                except Exception as e:
                    logger.error(f'Error transcribing {username}: {e}', exc_info=True)
                    continue
            
            # Generate per-person summaries
            if user_transcriptions:
                await ctx.send("🤖 Generating individual summaries and task lists...")
                
                for user_id, transcription_data in user_transcriptions.items():
                    username = transcription_data['username']
                    text = transcription_data['text']
                    
                    try:
                        logger.info(f'Generating summary for {username}...')
                        person_summary = await summarizer.summarize_person_tasks(
                            text, 
                            username, 
                            language=None
                        )
                        user_summaries[user_id] = {
                            'username': username,
                            'summary': person_summary,
                            'transcription': text
                        }
                        logger.info(f'✓ Generated summary for {username}')
                    except Exception as e:
                        logger.error(f'Error generating summary for {username}: {e}')
                        user_summaries[user_id] = {
                            'username': username,
                            'summary': f"Error generating summary: {str(e)}",
                            'transcription': text
                        }
                
                # Display results
                await display_person_summaries(ctx, user_summaries, channel_name, started_at)
                
                # Only generate combined summary if there are multiple participants
                # (to avoid duplication when there's only one person)
                if len(user_transcriptions) > 1:
                    all_transcriptions = [t for t in user_transcriptions.values()]
                    try:
                        await summarize_transcriptions(ctx, all_transcriptions, channel_name)
                    except Exception as e:
                        logger.error(f'Error saving combined note: {e}', exc_info=True)
                        # Don't fail the whole process if combined note fails
                else:
                    # For single participant, also show the general summary
                    logger.info('Single participant detected - generating general summary...')
                    all_transcriptions = [t for t in user_transcriptions.values()]
                    try:
                        # Generate and show the general summary
                        logger.info(f'Formatting {len(all_transcriptions)} transcriptions for general summary...')
                        formatted_transcriptions = [format_transcription_for_summary(t) for t in all_transcriptions]
                        conversation_text = '\n'.join(formatted_transcriptions)
                        logger.info(f'Conversation text length: {len(conversation_text)} characters')
                        
                        logger.info('Calling summarizer.summarize() for general summary...')
                        summary = await summarizer.summarize(conversation_text, channel_name, language=None)
                        logger.info(f'General summary generated: {len(summary)} characters')
                        
                        note = note_manager.save_note(
                            channel_id=ctx.channel.id,
                            channel_name=channel_name,
                            messages=all_transcriptions,
                            summary=summary,
                            timestamp=datetime.now()
                        )
                        logger.info(f'Note saved with ID: {note["id"]}')
                        
                        # Show the general summary
                        logger.info('Sending general summary embed to Discord...')
                        embed = discord.Embed(
                            title=f"📝 Summary: {channel_name}",
                            description=summary,
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="Transcriptions", value=len(all_transcriptions), inline=True)
                        embed.add_field(name="Note ID", value=note['id'], inline=True)
                        embed.set_footer(text="AI Notetaker Bot")
                        await ctx.send(embed=embed)
                        logger.info(f'✓ General summary sent to Discord successfully')
                    except Exception as e:
                        logger.error(f'❌ CRITICAL ERROR saving/showing general summary: {e}', exc_info=True)
                        await ctx.send(f"⚠️ Error generating general summary: {str(e)}")
            else:
                logger.warning('No transcriptions collected from any users')
                logger.warning('Falling back to combined audio file transcription')
                # Clear user_audio_files flag so we try combined file - DON'T remove session yet
                user_audio_files = {}
            
            # Only remove session if we successfully got transcriptions
            if user_transcriptions:
                if voice_channel_id in recording_sessions:
                    del recording_sessions[voice_channel_id]
                    logger.debug(f'Removed session for channel {voice_channel_id} after transcription')
                
        except Exception as e:
            logger.error(f'Error processing per-user transcriptions: {e}', exc_info=True)
            logger.warning('Falling back to combined audio file transcription')
            # Fall through to try combined file as backup - DON'T remove session yet
            user_audio_files = {}
    
    # Fallback: Use combined audio file if per-user files not available or failed
    if not user_audio_files and audio_file and os.path.exists(audio_file):
        # Fallback to combined transcription if per-user files not available
        file_size = os.path.getsize(audio_file)
        logger.info(f'Starting transcription of {os.path.basename(audio_file)} ({file_size} bytes)')
        
        if file_size == 0:
            logger.error(f'Audio file is empty: {audio_file}')
            await ctx.send("⚠️ Audio file was created but is empty. Please check your microphone settings.")
            if voice_channel_id in recording_sessions:
                del recording_sessions[voice_channel_id]
            return
        
        logger.info(f'Using combined audio file (fallback mode): {audio_file}')
        await ctx.send("📝 Transcribing audio... This may take a moment.")

        try:
            with open(audio_file, 'rb') as f:
                audio_data = f.read()
            
            logger.debug(f'Read {len(audio_data)} bytes from combined audio file')
                
            if not audio_data or len(audio_data) < 1000:
                logger.warning(f'Audio file too small: {len(audio_data)} bytes')
                await ctx.send("⚠️ Audio file appears to be empty or too small.")
                if voice_channel_id in recording_sessions:
                    del recording_sessions[voice_channel_id]
                return
                
            audio_buffer = io.BytesIO(audio_data)
            audio_buffer.seek(0)

            logger.info('Starting transcription of combined audio...')
            logger.info(f'Audio file details: {os.path.basename(audio_file)}, {len(audio_data)} bytes')
            
            transcription_text = await transcriber.transcribe_audio(audio_buffer, 0)
            
            logger.info(f'Transcription result: type={type(transcription_text)}, value={repr(transcription_text[:200]) if transcription_text else None}, length={len(transcription_text) if transcription_text else 0}')
            
            # More lenient check - accept any non-None result
            if transcription_text is not None:
                # Even if empty string, try to process it (might have whitespace-only content)
                stripped = transcription_text.strip() if transcription_text else ""
                if stripped:
                    logger.info(f'✓ Transcription successful: {len(transcription_text)} characters')
                    logger.info(f'Transcription preview: {transcription_text[:200]}')
                    transcription_entry = {
                        'user_id': 0,
                        'text': transcription_text,
                        'timestamp': started_at
                    }
                    await summarize_transcriptions(ctx, [transcription_entry], channel_name)
                else:
                    # Empty or whitespace-only - this is a real problem
                    logger.error(f'❌ CRITICAL: Transcription returned empty/whitespace string!')
                    logger.error(f'  - Audio file: {audio_file} ({len(audio_data)} bytes)')
                    logger.error(f'  - Transcription type: {type(transcription_text)}')
                    logger.error(f'  - Transcription value: {repr(transcription_text)}')
                    logger.error(f'  - This means Whisper processed the audio but found no speech')
                    logger.error(f'  - Possible causes: audio too quiet, wrong format, or Whisper model issue')
                    await ctx.send("⚠️ No speech was detected in the recording. Check bot logs for details.")
            else:
                # None result - transcription failed completely
                logger.error(f'❌ CRITICAL: Transcription returned None!')
                logger.error(f'  - Audio file: {audio_file} ({len(audio_data)} bytes)')
                logger.error(f'  - This means Whisper failed to process the audio')
                logger.error(f'  - Possible causes: audio format issue, file corruption, or Whisper error')
                await ctx.send("⚠️ Transcription failed. Check bot logs for details.")
            
            if voice_channel_id in recording_sessions:
                del recording_sessions[voice_channel_id]
                
        except Exception as e:
            logger.error(f'Error transcribing audio file: {e}', exc_info=True)
            await ctx.send(f"❌ Error transcribing audio: {str(e)}")
            if voice_channel_id in recording_sessions:
                del recording_sessions[voice_channel_id]
    else:
        # Transcription already happened above, don't show any error message
        logger.debug('Reached else block - transcription already completed')
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
