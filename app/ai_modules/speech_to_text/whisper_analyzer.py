"""Whisper Speech-to-Text analyzer plugin (faster-whisper)."""

import logging
import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel

from app.ai_modules.base.analyzer_interface import (
    AnalysisResult,
    AnalyzerInterface,
    AnalyzerUnavailable,
)
from app.ai_modules.registry import register_analyzer
from app.core.config.settings import settings

logger = logging.getLogger(__name__)


def _add_nvidia_dll_dirs() -> None:
    """Expose NVIDIA runtime DLL (cuBLAS/cuDNN) ke ctranslate2.

    ctranslate2 butuh cublas64_12.dll yang dipasok package nvidia-cublas-cu12.
    os.add_dll_directory saja tidak cukup untuk ctranslate2 (dia pakai search
    PATH klasik saat lazy-load cuBLAS saat encode), jadi bin dir juga di-prepend
    ke PATH. Idempoten.
    """
    if sys.platform != "win32":
        return
    if getattr(_add_nvidia_dll_dirs, "_done", False):
        return
    dirs = [
        Path(sys.prefix) / "Lib" / "site-packages" / sub
        for sub in ("nvidia/cublas/bin", "nvidia/cuda_nvrtc/bin", "nvidia/cudnn/bin")
    ]
    dirs = [d for d in dirs if d.is_dir()]
    for d in dirs:
        try:
            os.add_dll_directory(str(d))
        except (OSError, ValueError):
            pass
    existing = os.environ.get("PATH", "")
    prepend = os.pathsep.join(str(d) for d in dirs)
    if prepend and not any(str(d) in existing for d in dirs):
        os.environ["PATH"] = prepend + os.pathsep + existing
    _add_nvidia_dll_dirs._done = True


@register_analyzer
class WhisperAnalyzer(AnalyzerInterface):
    """Transcription analyzer menggunakan faster-whisper.

    analyzer_type "whisper". Bukan scorer — score selalu 5.0 (netral),
    hasil transcription ada di result_data.
    """

    analyzer_type = "whisper"

    def __init__(self) -> None:
        """Initialize config; model di-load lazy di analyze()."""
        self.model_size = settings.WHISPER_MODEL
        self.device = settings.WHISPER_DEVICE
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        self.model = None

    def _load_model(self) -> WhisperModel:
        """Lazy load whisper model untuk hemat memori."""
        if self.model is None:
            _add_nvidia_dll_dirs()
            # Disable MediaPipe telemetry — clearcut uploader retry loop
            # bikin transcription lambat di Windows.
            os.environ.setdefault("MEDIAPIPE_DISABLE_TELEMETRY", "1")
            os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
            os.environ.setdefault("GLOG_minloglevel", "3")
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self.model

    def analyze(self, input: dict) -> AnalysisResult:
        """Transcribe audio file.

        input: {"audio_path": str, "language": str | None}.
        """
        audio_path = input.get("audio_path", "")
        language = input.get("language")

        if not Path(audio_path).exists():
            raise AnalyzerUnavailable(f"Audio file not found at: {audio_path}")

        model = self._load_model()
        logger.info("Transcribing audio: %s", audio_path)

        segments, info = model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            beam_size=5,
        )

        detected_language = info.language
        full_text_list = []
        transcribed_segments = []

        for seg in segments:
            full_text_list.append(seg.text)

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
        logger.info("Transcription completed. Detected language: %s", detected_language)

        return AnalysisResult(
            score=5.0,
            result_data={
                "reason": "Hasil speech-to-text (faster-whisper)",
                "language": detected_language,
                "full_text": full_text,
                "segments": transcribed_segments,
            },
        )