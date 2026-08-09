"""Audio quality analyzer (librosa).

Kualitas audio: SNR proxy (noise floor), clipping detection, spectral flatness.
Clean/high-SNR → skor tinggi; noise/clipping/echo → rendah.
"""

import logging
from pathlib import Path

import librosa
import numpy as np

from app.ai_modules.base.analyzer_interface import (
    AnalysisResult,
    AnalyzerInterface,
    AnalyzerUnavailable,
)
from app.ai_modules.registry import register_analyzer

logger = logging.getLogger(__name__)


@register_analyzer
class AudioQualityAnalyzer(AnalyzerInterface):
    """Skor kualitas audio dari window audio."""

    analyzer_type = "audio"

    def analyze(self, input: dict) -> AnalysisResult:
        """Analisis kualitas audio.

        input: {"audio_path": str, "start": float, "end": float}.
        """
        audio_path = input.get("audio_path", "")
        start = float(input.get("start", 0.0))
        end = float(input.get("end", 0.0))

        if not audio_path or not Path(audio_path).exists():
            raise AnalyzerUnavailable(f"Audio tidak tersedia: {audio_path}")

        try:
            y, sr = librosa.load(audio_path, sr=None, offset=start, duration=max(end - start, 0.1))
        except Exception as e:
            raise AnalyzerUnavailable(f"Gagal baca audio: {e}")

        if len(y) == 0:
            return AnalysisResult(
                score=5.0,
                result_data={"reason": "Audio kosong dalam window"},
            )

        # Clipping: amplitudo nyaris penuh (> 0.99)
        clipping_ratio = float(np.mean(np.abs(y) > 0.99))

        # SNR proxy: energi median (speech) vs percentil 10 (noise floor)
        window = np.abs(y)
        speech_level = np.median(window)
        noise_level = np.percentile(window, 10)
        snr_db = 20 * np.log10(np.clip(speech_level / max(noise_level, 1e-8), 1e-4, None))

        # Spectral flatness: 0 (tonal) - 1 (noise-like)
        flatness = float(np.mean(librosa.feature.spectral_flatness(y=y)))

        # Skor 0-10: SNR tinggi bagus, clipping buruk, flatness ekstrem = noise
        snr_score = min(max((snr_db - 5.0) / 30.0, 0.0), 1.0)
        clipping_penalty = clipping_ratio * 3.0
        flatness_score = 1.0 - min(abs(flatness - 0.25) / 0.45, 1.0)

        final = round(min(5.0 + snr_score * 3.0 + flatness_score * 2.0 - clipping_penalty, 10.0), 2)
        final = max(0.0, final)

        return AnalysisResult(
            score=final,
            result_data={
                "reason": "Kualitas audio dari librosa (SNR + clipping + spectral flatness)",
                "snr_db": round(float(snr_db), 2),
                "clipping_ratio": round(clipping_ratio, 4),
                "spectral_flatness": round(flatness, 4),
            },
        )
