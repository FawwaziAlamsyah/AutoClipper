"""Voice emotion analyzer (librosa).

Analisis energi emosi dari audio: pitch (librosa.yin), RMS energy, zero-crossing
rate, loudness (dBFS). Variasi RMS tinggi + pitch range lebar = emosi "menyala";
datar/quiet = netral.
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
class VoiceEmotionAnalyzer(AnalyzerInterface):
    """Skor emosi vokal dari fitur audio librosa."""

    analyzer_type = "voice_emotion"

    def analyze(self, input: dict) -> AnalysisResult:
        """Analisis window audio.

        input: {"audio_path": str, "start": float, "end": float}.
        """
        audio_path = input.get("audio_path", "")
        start = float(input.get("start", 0.0))
        end = float(input.get("end", 0.0))

        if not audio_path or not Path(audio_path).exists():
            raise AnalyzerUnavailable(f"Audio tidak tersedia: {audio_path}")

        try:
            # Load window [start, end] (offset/duration dalam detik)
            y, sr = librosa.load(audio_path, sr=None, offset=start, duration=max(end - start, 0.1))
        except Exception as e:
            raise AnalyzerUnavailable(f"Gagal baca audio: {e}")

        if len(y) == 0:
            return AnalysisResult(
                score=5.0,
                result_data={"reason": "Audio kosong dalam window"},
            )

        rms = librosa.feature.rms(y=y)[0]
        zcr = librosa.feature.zero_crossing_rate(y)[0]

        # dbFS loudness (avoid log(0))
        rms_db = 20 * np.log10(np.clip(rms, 1e-8, None))

        # Pitch via YIN (frame-based)
        pitches = librosa.yin(y, fmin=80, fmax=400)

        avg_rms_db = float(np.mean(rms_db))
        rms_std = float(np.std(rms_db))
        pitch_std = float(np.std(pitches))
        avg_zcr = float(np.mean(zcr))

        # Skor emosi: aktifnya pembicaraan (energi + variasi pitch)
        loudness_score = min(max((avg_rms_db + 40.0) / 10.0, 0.0), 1.0)
        energy_variation = min(rms_std / 8.0, 1.0)
        pitch_range = min(pitch_std / 40.0, 1.0)
        activity = min(avg_zcr / 0.08, 1.0)

        final = round(min(5.0 + loudness_score * 2.0 + energy_variation * 1.5 + pitch_range * 1.0 + activity * 0.5, 10.0), 2)

        return AnalysisResult(
            score=final,
            result_data={
                "reason": "Emosi vokal dari librosa (loudness + variasi RMS + pitch + aktivitas)",
                "avg_loudness_db": round(avg_rms_db, 2),
                "rms_variation_db": round(rms_std, 2),
                "pitch_std_hz": round(pitch_std, 2),
                "avg_zero_crossing_rate": round(avg_zcr, 4),
            },
        )
