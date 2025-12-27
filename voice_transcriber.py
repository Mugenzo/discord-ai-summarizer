"""
Voice Transcription using Whisper (local installation)
"""

import io
import tempfile
import os
from typing import Optional


class VoiceTranscriber:
    """Handles voice transcription using local Whisper installation."""

    def __init__(self, ollama_api_url: str = 'http://localhost:11434', model_name: str = 'medium'):
        # Keep for compatibility, but we only use local Whisper
        self.ollama_api_url = ollama_api_url.rstrip('/')
        self.model_name = model_name
        self._whisper_model = None

    def _load_whisper_model(self):
        """Lazy load Whisper model (only load once)."""
        if self._whisper_model is None:
            try:
                import whisper
                # Load whisper model
                # Options: tiny, base, small, medium, large, large-v2, large-v3
                # medium is recommended for good accuracy/speed balance
                # large-v3 is best accuracy but slower
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Loading Whisper model '{self.model_name}' (this may take a moment on first use)...")
                logger.info(f"Note: First-time download may take several minutes depending on model size.")
                self._whisper_model = whisper.load_model(self.model_name)
                logger.info(f"Whisper model '{self.model_name}' loaded successfully!")
            except ImportError:
                raise ImportError(
                    "Whisper not installed. Install with: pip install openai-whisper"
                )
        return self._whisper_model

    async def transcribe_audio(self, audio_file: io.BytesIO, user_id: int) -> Optional[str]:
        """Transcribe audio file to text."""
        try:
            # Reset file pointer
            audio_file.seek(0)
            audio_data = audio_file.read()

            if not audio_data:
                return None

            # Use local Whisper
            return await self._transcribe_with_whisper(audio_data)

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Transcription error: {e}")
            return None

    async def _transcribe_with_whisper(self, audio_data: bytes) -> Optional[str]:
        """Transcribe using local Whisper installation."""
        try:
            import asyncio

            # Run Whisper in executor to avoid blocking
            loop = asyncio.get_event_loop()

            # Save audio to temp file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_file.write(audio_data)
                tmp_path = tmp_file.name

            try:
                # Load model (cached after first load)
                model = await loop.run_in_executor(None, self._load_whisper_model)

                # Transcribe in executor with better settings for accuracy
                result = await loop.run_in_executor(
                    None,
                    lambda: model.transcribe(
                        tmp_path,
                        fp16=False,  # Use fp32 for better accuracy (M1 Macs handle this well)
                        language=None,  # Auto-detect language
                        task="transcribe",  # Explicitly transcribe (not translate)
                        verbose=False  # Don't print progress
                    )
                )

                return result["text"].strip()
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except ImportError as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error: {e}")
            logger.error("Please install Whisper: pip install openai-whisper")
            return None
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Whisper transcription error: {e}")
            return None

