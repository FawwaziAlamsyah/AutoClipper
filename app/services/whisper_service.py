"""Whisper Speech-to-Text service using faster-whisper."""

import logging
from pathlib import Path

from faster_whisper import WhisperModel

from app.core.config.settings import settings

logger = logging.getLogger(__name__)


class WhisperService:
    """Transcription service using faster-whisper model."""

    def __init__(self) -> None:
        """Initialize the model based on app configuration."""
        self.model_size = settings.WHISPER_MODEL
        self.device = settings.WHISPER_DEVICE

        # Deteksi device secara otomatis
        if self.device == "auto":
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"

        # Jika cuda dipilih tetapi tidak disupport, fallback ke cpu
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        
        logger.info(
            "Initializing Faster-Whisper: model=%s, device=%s, compute=%s",
            self.model_size,
            self.device,
            self.compute_type,
        )
        self.model = None

    def _load_model(self) -> WhisperModel:
        """Lazy load the whisper model to save memory."""
        if self.model is None:
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self.model

    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        """Transcribe an audio file and return segment details with word timestamps.

        Args:
            audio_path: Path to wav file.
            language: Optional language code (e.g. 'id', 'en').

        Returns:
            Dict containing language, full_text, and list of segments with word timestamps.
        """
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found at: {audio_path}")

        model = self._load_model()
        logger.info("Transcribing audio: %s", audio_path)

        segments, info = model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            beam_size=5,
        )

        detected_language = info.language
        logger.info("Transcription completed. Detected language: %s", detected_language)

        full_text_list = []
        transcribed_segments = []

        for seg in segments:
            full_text_list.append(seg.text)
            
            # Ekstrak data kata-kata (word-level timestamps) jika ada
            words_list = []
            if seg.words:
                for w in seg.words:
                    words_list.append({
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    })

            transcribed_segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": words_list,
            })

        full_text = "".join(full_text_list).strip()

        return {
            "language": detected_language,
            "full_text": full_text,
            "segments": transcribed_segments,
        }
