"""
Audio receiver for Discord voice channels
Receives and decodes RTP/Opus packets from voice websocket
"""

import struct
import asyncio
from collections import defaultdict
from datetime import datetime
import io
import wave

try:
    import opuslib
except ImportError:
    opuslib = None


class AudioReceiver:
    """Receives and decodes audio from Discord voice websocket."""

    def __init__(self, voice_client, session):
        self.voice_client = voice_client
        self.session = session
        self.audio_buffers = session['audio_buffers']
        self.decoder = None
        self.running = False
        self.last_transcription = defaultdict(lambda: datetime.now())
        self.TRANSCRIPTION_INTERVAL = 10  # Transcribe every 10 seconds
        self.ssrc_to_user = {}  # Map SSRC to user_id

    def _init_decoder(self):
        """Initialize Opus decoder."""
        if opuslib is None:
            raise ImportError("opuslib not installed. Run: pip install opuslib")

        try:
            # Opus decoder: 48000 Hz, 2 channels (stereo), 20ms frame size
            self.decoder = opuslib.Decoder(48000, 2)
        except Exception as e:
            error_msg = str(e)
            if "Could not find Opus library" in error_msg or "opus" in error_msg.lower():
                raise ImportError(
                    "Opus system library not found. On macOS, install with: brew install opus\n"
                    "On Linux: sudo apt-get install libopus-dev (Ubuntu/Debian) or equivalent"
                )
            raise

    async def start(self):
        """Start receiving audio."""
        if self.decoder is None:
            self._init_decoder()

        self.running = True
        asyncio.create_task(self._receive_loop())

    async def _receive_loop(self):
        """Main loop to receive and process audio packets."""
        try:
            # Access the voice websocket - try different ways discord.py might expose it
            ws = None
            if hasattr(self.voice_client, 'ws'):
                ws = self.voice_client.ws
            elif hasattr(self.voice_client, '_connection') and hasattr(self.voice_client._connection, 'ws'):
                ws = self.voice_client._connection.ws
            elif hasattr(self.voice_client, '_websocket'):
                ws = self.voice_client._websocket

            if not ws:
                print('[AudioReceiver] Could not access voice websocket')
                return

            print('[AudioReceiver] Starting audio receive loop...')

            while self.running and self.voice_client.is_connected():
                try:
                    # Receive packet from websocket (with timeout)
                    if hasattr(ws, 'recv'):
                        packet = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    else:
                        # Try alternative receive method
                        packet = await asyncio.wait_for(ws.receive(), timeout=1.0)

                    if packet:
                        # Handle different packet formats
                        if isinstance(packet, bytes):
                            await self._process_packet(packet)
                        elif hasattr(packet, 'data'):
                            await self._process_packet(packet.data)
                        elif isinstance(packet, tuple) and len(packet) >= 2:
                            # Might be (user_id, audio_data) format
                            user_id, audio_data = packet[0], packet[1]
                            if user_id and audio_data:
                                await self._process_audio_data(user_id, audio_data)

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f'[AudioReceiver] Error receiving packet: {e}')
                    await asyncio.sleep(0.1)

        except Exception as e:
            print(f'[AudioReceiver] Receive loop ended: {e}')

    async def _process_packet(self, packet: bytes):
        """Process a single RTP packet."""
        try:
            # Parse RTP header (12 bytes minimum)
            if len(packet) < 12:
                return

            # Extract SSRC (user identifier) from RTP header (bytes 8-12)
            ssrc = struct.unpack('>I', packet[8:12])[0]

            # Extract Opus payload (skip 12-byte RTP header, may have extension)
            # RTP header: 12 bytes, but can have CSRC list and extension
            header_length = 12
            if len(packet) > 12:
                # Check for extension bit (bit 4 of byte 0)
                if (packet[0] & 0x10):
                    # Has extension, skip it
                    ext_length = struct.unpack('>H', packet[header_length:header_length+2])[0]
                    header_length += 2 + (ext_length * 4)

            opus_data = packet[header_length:]

            if not opus_data or self.decoder is None:
                return

            # Decode Opus to PCM
            try:
                # Opus frame is 20ms at 48kHz = 960 samples per channel
                pcm_data = self.decoder.decode(opus_data, 960)

                # Get user_id from SSRC mapping
                user_id = self._ssrc_to_user_id(ssrc)

                if user_id:
                    await self._process_audio_data(user_id, pcm_data)
            except Exception as decode_error:
                # Opus decode error - skip this packet
                pass

        except Exception as e:
            print(f'[AudioReceiver] Error processing packet: {e}')

    async def _process_audio_data(self, user_id: int, pcm_data: bytes):
        """Process decoded PCM audio data for a user."""
        # Add to buffer
        if user_id not in self.audio_buffers:
            self.audio_buffers[user_id] = []
        self.audio_buffers[user_id].append(pcm_data)

        # Check if we should transcribe
        time_since = (datetime.now() - self.last_transcription[user_id]).total_seconds()
        if time_since >= self.TRANSCRIPTION_INTERVAL and len(self.audio_buffers[user_id]) > 0:
            asyncio.create_task(self._transcribe_user(user_id))
            self.last_transcription[user_id] = datetime.now()

    def _ssrc_to_user_id(self, ssrc: int):
        """Map SSRC to user_id."""
        # Check our mapping first
        if ssrc in self.ssrc_to_user:
            return self.ssrc_to_user[ssrc]

        # Try to get from voice client's internal mapping
        if hasattr(self.voice_client, '_ssrc_to_id'):
            user_id = self.voice_client._ssrc_to_id.get(ssrc)
            if user_id:
                self.ssrc_to_user[ssrc] = user_id
                return user_id

        # Try to get from voice states in the channel
        if hasattr(self.voice_client, 'channel') and self.voice_client.channel:
            for member in self.voice_client.channel.members:
                if hasattr(member, 'voice') and member.voice:
                    # Voice state might have SSRC info
                    # This is a fallback - may not always work
                    pass

        return None

    def update_ssrc_mapping(self, user_id: int, ssrc: int):
        """Update SSRC to user mapping."""
        self.ssrc_to_user[ssrc] = user_id

    async def _transcribe_user(self, user_id: int):
        """Transcribe buffered audio for a user."""
        if user_id not in self.audio_buffers or not self.audio_buffers[user_id]:
            return

        # Get audio data
        audio_data = b''.join(self.audio_buffers[user_id])
        self.audio_buffers[user_id] = []

        if len(audio_data) < 1000:  # Too short, skip
            return

        # Create WAV file
        wav_buffer = io.BytesIO()
        try:
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(2)  # Stereo
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(48000)
                wav_file.writeframes(audio_data)

            wav_buffer.seek(0)

            # Import transcriber here to avoid circular imports
            from voice_transcriber import VoiceTranscriber
            transcriber = VoiceTranscriber()

            transcription_text = await transcriber.transcribe_audio(wav_buffer, user_id)

            if transcription_text and transcription_text.strip():
                transcription_entry = {
                    'user_id': user_id,
                    'text': transcription_text,
                    'timestamp': datetime.now()
                }
                self.session['transcriptions'].append(transcription_entry)
                print(f'[Transcription] User {user_id}: {transcription_text[:100]}...')

        except Exception as e:
            print(f'[AudioReceiver] Error transcribing: {e}')

    def stop(self):
        """Stop receiving audio."""
        self.running = False

