"""Local audio transcription service using faster-whisper."""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)


class TranscriptionResult(BaseModel):
    """Result of audio transcription."""

    text: str
    language: str
    duration_seconds: float
    segments: list[dict]


class TranscriptionService:
    """Service for transcribing audio using faster-whisper.

    Uses the faster-whisper library for efficient local transcription.
    Model is loaded lazily on first use.
    
    Supports: WAV, MP3, M4A, WEBM, OGG, FLAC (via PyAV)
    """

    _model = None
    _model_size = None  # Will be loaded from settings

    @classmethod
    def get_model(cls):
        """Get or load the whisper model (lazy loading)."""
        if cls._model is None:
            from faster_whisper import WhisperModel

            # Get model size from settings if not already set
            if cls._model_size is None:
                settings = get_settings()
                cls._model_size = settings.whisper_model

            logger.info(f"Loading Whisper model: {cls._model_size}")

            # Use int8 for CPU efficiency, or float16 for GPU
            cls._model = WhisperModel(
                cls._model_size,
                device="cpu",
                compute_type="int8",
            )
            logger.info("Whisper model loaded successfully")
        return cls._model

    @classmethod
    def set_model_size(cls, size: str):
        """Set the model size before first use.

        Args:
            size: Model size (tiny, base, small, medium, large-v3)
        """
        if cls._model is not None:
            raise RuntimeError("Cannot change model size after model is loaded")
        cls._model_size = size

    def transcribe_audio(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio data to text.

        Args:
            audio_data: Raw audio bytes (supports WAV, MP3, WEBM, etc.)
            language: Optional language code (e.g., 'en', 'es'). Auto-detected if not provided.
            filename: Optional filename hint for format detection

        Returns:
            TranscriptionResult with text and metadata
        """
        model = self.get_model()

        # Determine file suffix from filename
        suffix = ".wav"
        if filename:
            if "." in filename:
                suffix = "." + filename.rsplit(".", 1)[1].lower()

        logger.info(f"Transcribing audio: {len(audio_data)} bytes, format: {suffix}")

        # Write audio to temp file (faster-whisper requires file path)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_data)
            temp_path = f.name

        try:
            # Transcribe
            # Default to English if not specified, to avoid misdetection
            segments, info = model.transcribe(
                temp_path,
                language=language or "en",
                beam_size=5,
                word_timestamps=False,
                vad_filter=False,
            )

            # Collect segments
            segment_list = []
            full_text_parts = []

            for segment in segments:
                segment_list.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                })
                full_text_parts.append(segment.text.strip())

            full_text = " ".join(full_text_parts)

            logger.info(
                f"Transcription complete: {info.duration:.1f}s audio, "
                f"{len(full_text)} chars, language={info.language}"
            )

            return TranscriptionResult(
                text=full_text,
                language=info.language,
                duration_seconds=info.duration,
                segments=segment_list,
            )

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise

        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

    def transcribe_file(
        self,
        file_path: str,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            file_path: Path to audio file
            language: Optional language code

        Returns:
            TranscriptionResult with text and metadata
        """
        with open(file_path, "rb") as f:
            audio_data = f.read()
        return self.transcribe_audio(audio_data, language, filename=file_path)
