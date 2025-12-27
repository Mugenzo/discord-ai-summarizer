"""
Custom audio recorder for Discord voice channels
Records audio using voice client's receive functionality
"""

import io
import wave
import struct
from typing import Dict, Optional
from collections import defaultdict


class AudioRecorder:
    """Records audio from Discord voice channels."""

    def __init__(self):
        self.recordings: Dict[int, Dict] = defaultdict(lambda: {
            'audio_data': [],
            'sample_rate': 48000,
            'channels': 2
        })

    def start_recording(self, user_id: int):
        """Start recording for a user."""
        self.recordings[user_id]['audio_data'] = []

    def add_audio_packet(self, user_id: int, pcm_data: bytes):
        """Add an audio packet to the recording."""
        if user_id in self.recordings:
            self.recordings[user_id]['audio_data'].append(pcm_data)

    def stop_recording(self, user_id: int) -> Optional[io.BytesIO]:
        """Stop recording and return WAV file as BytesIO."""
        if user_id not in self.recordings or not self.recordings[user_id]['audio_data']:
            return None

        recording = self.recordings[user_id]
        audio_data = b''.join(recording['audio_data'])

        if not audio_data:
            return None

        # Create WAV file
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(recording['channels'])
            wav_file.setsampwidth(2)  # 16-bit audio
            wav_file.setframerate(recording['sample_rate'])
            wav_file.writeframes(audio_data)

        wav_buffer.seek(0)

        # Clear recording
        del self.recordings[user_id]

        return wav_buffer

