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
                import torch
                # Load whisper model
                # Options: tiny, base, small, medium, large, large-v2, large-v3
                # medium is recommended for good accuracy/speed balance
                # large-v3 is best accuracy but slower
                import logging
                logger = logging.getLogger(__name__)
                
                # Check for GPU availability
                # Use GPU if available, otherwise fall back to CPU
                device = "cuda" if torch.cuda.is_available() else "cpu"
                
                if device == "cuda":
                    try:
                        # Quick test to ensure GPU actually works
                        test_tensor = torch.zeros(1).cuda()
                        _ = test_tensor + 1
                        del test_tensor
                        torch.cuda.empty_cache()
                        logger.info(f"✓ GPU detected: {torch.cuda.get_device_name(0)}")
                        logger.info(f"✓ CUDA version: {torch.version.cuda}")
                        logger.info(f"✓ GPU compute capability: {torch.cuda.get_device_capability(0)}")
                    except Exception as e:
                        logger.warning(f"⚠ GPU detected but not working: {str(e)[:100]}")
                        logger.warning("⚠ Falling back to CPU (transcription will be slower)")
                        device = "cpu"
                else:
                    logger.info("⚠ GPU not available, using CPU (transcription will be slower)")
                
                logger.info(f"Loading Whisper model '{self.model_name}' on {device} (this may take a moment on first use)...")
                logger.info(f"Note: First-time download may take several minutes depending on model size.")
                
                # Load model with error handling
                try:
                    self._whisper_model = whisper.load_model(self.model_name, device=device)
                    logger.info(f"✓ Whisper model '{self.model_name}' loaded successfully on {device}!")
                except Exception as e:
                    # If loading on GPU fails, try CPU as fallback
                    if device == "cuda":
                        logger.warning(f"Failed to load model on GPU: {e}")
                        logger.warning("Retrying on CPU...")
                        device = "cpu"
                        self._whisper_model = whisper.load_model(self.model_name, device="cpu")
                        logger.info(f"✓ Whisper model '{self.model_name}' loaded successfully on CPU!")
                    else:
                        raise
            except ImportError:
                raise ImportError(
                    "Whisper not installed. Install with: pip install openai-whisper"
                )
        return self._whisper_model
    
    def _is_gpu_available(self) -> bool:
        """Check if GPU (CUDA) is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    async def transcribe_audio(self, audio_file: io.BytesIO, user_id: int) -> Optional[str]:
        """Transcribe audio file to text."""
        try:
            import logging
            logger = logging.getLogger(__name__)
            
            # Reset file pointer
            audio_file.seek(0)
            audio_data = audio_file.read()

            if not audio_data:
                logger.error(f"Audio buffer is empty for user {user_id}")
                return None

            if len(audio_data) < 100:  # Very small files are likely empty
                logger.warning(f"Audio buffer very small: {len(audio_data)} bytes for user {user_id}")
                # Still try to transcribe - might be valid but short
            
            logger.info(f'Transcribing audio for user {user_id}: {len(audio_data)} bytes')
            result = await self._transcribe_with_whisper(audio_data)
            logger.info(f'Transcription result for user {user_id}: type={type(result)}, length={len(result) if result else 0}, preview={repr(result[:100]) if result else None}')
            return result

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Transcription error for user {user_id}: {e}", exc_info=True)
            return None

    async def _transcribe_with_whisper(self, audio_data: bytes) -> Optional[str]:
        """Transcribe using local Whisper installation."""
        try:
            import asyncio

            # Run Whisper in executor to avoid blocking
            loop = asyncio.get_event_loop()

            # Save audio to temp file - use .mp3 extension since we're receiving MP3 from Discord
            # Whisper can handle MP3, WAV, and other formats automatically
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                tmp_file.write(audio_data)
                tmp_path = tmp_file.name

            try:
                # Load model (cached after first load)
                model = await loop.run_in_executor(None, self._load_whisper_model)

                # Transcribe in executor with GPU-optimized settings
                # Use fp16=True for NVIDIA GPUs (faster, good accuracy)
                # Use fp16=False for CPU or M1 Macs (better accuracy on CPU)
                use_fp16 = self._is_gpu_available()
                
                # More aggressive transcription parameters to catch all speech
                result = await loop.run_in_executor(
                    None,
                    lambda: model.transcribe(
                        tmp_path,
                        fp16=use_fp16,  # fp16=True for NVIDIA GPUs (faster), fp16=False for CPU/M1 Macs
                        language=None,  # Auto-detect language
                        task="transcribe",  # Explicitly transcribe (not translate)
                        verbose=False,  # Don't print progress
                        condition_on_previous_text=False,  # Don't condition on previous text (better for short clips)
                        initial_prompt=None,  # No initial prompt
                        word_timestamps=False,  # Don't need word timestamps
                        prepend_punctuations='"\'' + '\xBF' + '([{-',  # Punctuation handling (¿ character)
                        append_punctuations='"\'.。,，!！?？:：")]}、',  # Punctuation handling
                        temperature=0.0,  # Deterministic (no randomness)
                        compression_ratio_threshold=2.4,  # Lower threshold to catch more speech
                        logprob_threshold=-1.0,  # Lower threshold to catch more speech
                        no_speech_threshold=0.6  # Lower threshold - accept more as speech (default is 0.6)
                    )
                )

                # Get text from result
                raw_text = result.get("text", "")
                transcribed_text = raw_text.strip() if raw_text else ""
                
                # Log transcription result for debugging
                import logging
                logger = logging.getLogger(__name__)
                
                # Debug: Log full result structure
                logger.info(f"Whisper result keys: {list(result.keys())}")
                logger.info(f"Whisper raw text: {repr(raw_text[:200]) if raw_text else 'EMPTY'}")
                logger.info(f"Whisper raw text length: {len(raw_text)}")
                logger.info(f"Whisper stripped text length: {len(transcribed_text)}")
                
                if transcribed_text:
                    logger.info(f"✓ Transcription successful: {len(transcribed_text)} characters")
                    logger.info(f"Transcription preview: {transcribed_text[:200]}")
                else:
                    logger.warning("⚠ Transcription returned empty text")
                    logger.warning(f"Raw text was: {repr(raw_text[:200])}")
                    # Check if there were any segments
                    segments = result.get("segments", [])
                    logger.warning(f"Segments found: {len(segments)}")
                    if segments:
                        logger.warning(f"First segment: {segments[0] if segments else 'N/A'}")
                        # Try to extract text from segments
                        segment_texts = []
                        for i, seg in enumerate(segments):
                            seg_text = seg.get("text", "").strip()
                            logger.debug(f"Segment {i}: {repr(seg_text[:100])}")
                            if seg_text:
                                segment_texts.append(seg_text)
                        
                        if segment_texts:
                            logger.warning(f"Found text in {len(segment_texts)} segments, combining...")
                            transcribed_text = " ".join(segment_texts).strip()
                            logger.info(f"✓ Recovered transcription from segments: {len(transcribed_text)} characters")
                            logger.info(f"Recovered text preview: {transcribed_text[:200]}")
                    else:
                        logger.error("No segments found in transcription result")
                        logger.error(f"Full result structure: {str(result)[:1000]}")

                # Return the text (even if empty, so bot can log it)
                if transcribed_text:
                    return transcribed_text
                else:
                    logger.error("FINAL: Returning None - no text found in transcription")
                    return None
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

