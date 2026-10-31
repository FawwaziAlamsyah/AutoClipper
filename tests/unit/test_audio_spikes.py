"""Unit tests for AudioSpikeDetectorService."""

from pathlib import Path
import numpy as np
import pytest

from app.services.audio_spike_detector_service import AudioSpikeDetectorService


def test_detect_timeline_spikes_synthetic(monkeypatch, tmp_path: Path):
    """Test deteksi multi-puncak audio pada timeline sintetis."""
    service = AudioSpikeDetectorService()

    # Buat file audio dummy
    audio_file = tmp_path / "dummy_audio.wav"
    audio_file.write_bytes(b"RIFF dummy wav header")

    # Buat audio 60 detik (sample_rate 8000)
    sr = 8000
    duration = 60.0
    total_samples = int(sr * duration)
    # Background noise tenang (-40 dBFS)
    audio = np.random.normal(0, 0.01, total_samples).astype(np.float32)

    # Tambahkan 2 lonjakan kuat di detik 15.0 dan detik 40.0
    s1_start = int(15.0 * sr)
    s1_end = int(16.5 * sr)
    audio[s1_start:s1_end] = np.random.normal(0, 0.4, s1_end - s1_start).astype(np.float32)

    s2_start = int(40.0 * sr)
    s2_end = int(41.5 * sr)
    audio[s2_start:s2_end] = np.random.normal(0, 0.5, s2_end - s2_start).astype(np.float32)

    # Mock _extract_audio_samples agar mengembalikan array sintetis
    monkeypatch.setattr(service, "_extract_audio_samples", lambda *args, **kwargs: audio)

    spikes = service.detect_timeline_spikes(audio_file, min_gap_seconds=10.0, sample_rate=sr)

    assert len(spikes) == 2
    # Spike pertama di sekitar 15s
    assert any(14.0 <= s["time"] <= 17.0 for s in spikes)
    # Spike kedua di sekitar 40s
    assert any(39.0 <= s["time"] <= 42.0 for s in spikes)
    # Memiliki format waktu MM:SS
    assert any(s["time_str"] == "00:15" or s["time_str"] == "00:16" for s in spikes)
