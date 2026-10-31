"""Audio Spike Detector Service — visual & acoustic emotion peak detection.

Mendeteksi lonjakan emosi/volume audio (teriakan, kaget, ketawa ngakak, jumpscare)
dari video/audio sumber untuk Auto Hook Retargeting dan AI Video Analysis.
"""

from __future__ import annotations

import io
import logging
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from app.core.config.settings import settings

logger = logging.getLogger(__name__)


class AudioSpikeDetectorService:
    """Service deteksi puncak lonjakan audio dan emosi vokal streamer."""

    def __init__(self, ffmpeg_path: str | None = None) -> None:
        self.ffmpeg_path = ffmpeg_path or getattr(settings, "FFMPEG_PATH", "ffmpeg")

    def detect_spikes(
        self,
        media_path: str | Path,
        start_time: float = 0.0,
        end_time: float | None = None,
        sample_rate: int = 16000,
    ) -> dict[str, Any]:
        """Deteksi lonjakan audio (spikes) pada rentang [start_time, end_time].

        Returns:
            dict dengan key:
                - has_spike: bool
                - peak_time: float (timestamp absolut video dalam detik)
                - peak_rel_time: float (detik relatif dari start_time)
                - peak_db: float (dBFS)
                - mean_db: float
                - spike_count: int
                - duration: float
        """
        path = Path(media_path)
        import os
        if not path.exists() or not os.path.exists(str(media_path)):
            logger.warning("AudioSpikeDetector: file tidak ditemukan: %s", path)
            return self._empty_result(start_time, end_time)

        duration = (end_time - start_time) if end_time is not None else 60.0
        if duration <= 0:
            return self._empty_result(start_time, end_time)

        audio_data = self._extract_audio_samples(path, start_time, duration, sample_rate)
        if audio_data is None or len(audio_data) < sample_rate * 0.2:
            return self._empty_result(start_time, end_time)

        actual_dur = len(audio_data) / sample_rate
        hop_len = int(sample_rate * 0.05)    # 50 ms hop
        frame_len = int(sample_rate * 0.1)   # 100 ms window

        # Hitung frame-based RMS
        num_frames = max(1, (len(audio_data) - frame_len) // hop_len + 1)
        rms = np.zeros(num_frames, dtype=np.float32)

        for i in range(num_frames):
            frame = audio_data[i * hop_len : i * hop_len + frame_len]
            rms[i] = np.sqrt(np.mean(frame**2)) if len(frame) > 0 else 0.0

        # Konversi ke dBFS
        db = 20.0 * np.log10(np.clip(rms, 1e-6, None))
        times_rel = np.arange(num_frames) * (hop_len / sample_rate)

        mean_db = float(np.mean(db))
        std_db = float(np.std(db))
        max_idx = int(np.argmax(db))
        peak_db = float(db[max_idx])
        peak_rel = float(times_rel[max_idx])

        # Ambang batas spike: di atas mean + 1.2*std ATAU di atas -16 dBFS
        threshold = max(mean_db + 1.2 * std_db, -18.0)
        spike_indices = np.where(db >= threshold)[0]
        has_spike = bool(len(spike_indices) > 0 and (peak_db - mean_db) >= 6.0)

        # Cari peak_time absolut
        peak_time = start_time + peak_rel

        return {
            "has_spike": has_spike,
            "peak_time": round(peak_time, 2),
            "peak_rel_time": round(peak_rel, 2),
            "peak_db": round(peak_db, 1),
            "mean_db": round(mean_db, 1),
            "spike_count": int(len(spike_indices)),
            "duration": round(actual_dur, 2),
        }

    def detect_timeline_spikes(
        self,
        media_path: str | Path,
        min_gap_seconds: float = 12.0,
        max_peaks: int = 35,
        sample_rate: int = 8000,
    ) -> list[dict[str, Any]]:
        """Scan timeline seluruh video/audio dan deteksi puncak lonjakan audio (teriakan/tawa/reaksi).

        Returns:
            list of dict: [
                {"time": 182.4, "time_str": "03:02", "spike_db": 14.5, "peak_db": -12.1},
                ...
            ] diurutkan berdasarkan timestamp secara ascending.
        """
        path = Path(media_path)
        if not path.exists():
            logger.warning("AudioSpikeDetector: File tidak ditemukan untuk timeline: %s", path)
            return []

        # Ekstrak audio mono downsampled 8kHz untuk seluruh file (sangat ringan dan cepat)
        audio_data = self._extract_audio_samples(
            path,
            start_time=0.0,
            duration=None,
            sample_rate=sample_rate,
            timeout=180,
        )
        if audio_data is None or len(audio_data) < sample_rate * 2.0:
            return []

        hop_len = int(sample_rate * 0.1)     # 100 ms hop
        frame_len = int(sample_rate * 0.2)   # 200 ms window
        num_frames = max(1, (len(audio_data) - frame_len) // hop_len + 1)
        rms = np.zeros(num_frames, dtype=np.float32)

        for i in range(num_frames):
            frame = audio_data[i * hop_len : i * hop_len + frame_len]
            rms[i] = np.sqrt(np.mean(frame**2)) if len(frame) > 0 else 0.0

        db = 20.0 * np.log10(np.clip(rms, 1e-6, None))
        times = np.arange(num_frames) * (hop_len / sample_rate)

        mean_db = float(np.mean(db))
        std_db = float(np.std(db))
        threshold = max(mean_db + 1.2 * std_db, -22.0)

        # Cari kandidat puncak lokal
        candidates: list[dict[str, Any]] = []
        min_gap_frames = int(min_gap_seconds / (hop_len / sample_rate))

        # Cari local maxima sederhana
        for i in range(1, num_frames - 1):
            if db[i] >= threshold and (db[i] - mean_db) >= 5.0:
                if db[i] >= db[i - 1] and db[i] >= db[i + 1]:
                    t = float(times[i])
                    mins = int(t // 60)
                    secs = int(t % 60)
                    candidates.append({
                        "frame_idx": i,
                        "time": round(t, 1),
                        "time_str": f"{mins:02d}:{secs:02d}",
                        "spike_db": round(float(db[i] - mean_db), 1),
                        "peak_db": round(float(db[i]), 1),
                    })

        if not candidates:
            return []

        # Sort berdasarkan kekuatan spike descending untuk non-maximum suppression berbasis min_gap
        candidates.sort(key=lambda x: x["spike_db"], reverse=True)
        selected: list[dict[str, Any]] = []

        for cand in candidates:
            # Pastikan tidak terlalu dekat dengan puncak yang sudah dipilih
            if any(abs(cand["time"] - s["time"]) < min_gap_seconds for s in selected):
                continue
            selected.append(cand)
            if len(selected) >= max_peaks:
                break

        # Urutkan kembali berdasarkan waktu ascending untuk timeline yang natural bagi LLM
        selected.sort(key=lambda x: x["time"])
        for item in selected:
            item.pop("frame_idx", None)

        return selected

    def get_hook_window_from_spike(
        self,
        peak_time: float,
        window_start: float,
        window_end: float,
        teaser_duration: float = 2.5,
    ) -> tuple[float, float]:
        """Tentukan rentang teaser cold-open [hook_start, hook_end] dari audio spike.

        Dimulai 0.75 detik sebelum puncak teriakan agar ekspresi sebelum teriak
        (windup/gasp) ikut tertangkap, berdurasi teaser_duration detik.
        """
        ideal_start = peak_time - 0.75
        min_start = window_start + 1.0 if (window_end - window_start) > 6.0 else window_start
        max_start = max(min_start, window_end - teaser_duration)

        start = max(min_start, min(ideal_start, max_start))
        end = min(window_end, start + teaser_duration)

        return round(start, 2), round(end, 2)

    def _extract_audio_samples(
        self,
        path: Path,
        start_time: float,
        duration: float | None,
        sample_rate: int,
        timeout: int = 30,
    ) -> np.ndarray | None:
        """Ekstrak audio slice via FFmpeg pipe (cepat & hemat memori)."""
        cmd = [
            self.ffmpeg_path,
            "-y",
        ]
        if start_time > 0.0:
            cmd.extend(["-ss", str(start_time)])
        if duration is not None and duration > 0:
            cmd.extend(["-t", str(duration)])
        cmd.extend([
            "-i", str(path),
            "-vn",
            "-f", "wav",
            "-ar", str(sample_rate),
            "-ac", "1",
            "-",
        ])
        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as proc:
                stdout_data, _ = proc.communicate(timeout=timeout)
                if proc.returncode == 0 and len(stdout_data) > 44:  # WAV header > 44 bytes
                    data, _ = sf.read(io.BytesIO(stdout_data), dtype="float32")
                    return data
        except Exception as e:
            logger.debug("AudioSpikeDetector FFmpeg pipe gagal: %s, coba fallback librosa", e)

        # Fallback ke librosa langsung jika ffmpeg pipe gagal
        try:
            import librosa
            dur_arg = duration if (duration is not None and duration > 0) else None
            data, _ = librosa.load(
                str(path),
                sr=sample_rate,
                mono=True,
                offset=max(0.0, start_time),
                duration=dur_arg,
            )
            return data
        except Exception as e:
            logger.warning("AudioSpikeDetector fallback librosa juga gagal: %s", e)
            return None

    @staticmethod
    def _empty_result(start: float, end: float | None) -> dict[str, Any]:
        duration = (end - start) if end is not None else 0.0
        return {
            "has_spike": False,
            "peak_time": round(start + duration / 2.0, 2),
            "peak_rel_time": round(duration / 2.0, 2),
            "peak_db": -99.0,
            "mean_db": -99.0,
            "spike_count": 0,
            "duration": round(duration, 2),
        }
