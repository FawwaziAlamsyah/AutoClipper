"""Unit tests for AudioSpikeDetectorService."""

from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from app.services.audio_spike_detector_service import AudioSpikeDetectorService


def test_empty_result_on_nonexistent_file(tmp_path):
    svc = AudioSpikeDetectorService()
    res = svc.detect_spikes(tmp_path / "not_exist.mp4", start_time=10.0, end_time=20.0)
    assert res["has_spike"] is False
    assert res["peak_db"] == -99.0


def test_detect_spikes_with_synthetic_audio(tmp_path):
    svc = AudioSpikeDetectorService()

    # Buat synthetic audio 5 detik dengan lonjakan di detik ke-3
    sr = 16000
    dur = 5.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    # Background quiet noise
    audio = 0.01 * np.sin(2 * np.pi * 440 * t)
    # Spike at 3.0s (amplified 20x)
    spike_idx_start = int(2.8 * sr)
    spike_idx_end = int(3.2 * sr)
    audio[spike_idx_start:spike_idx_end] = 0.8 * np.sin(2 * np.pi * 880 * t[spike_idx_start:spike_idx_end])

    dummy_file = tmp_path / "dummy.mp4"
    dummy_file.touch()

    with patch.object(svc, "_extract_audio_samples", return_value=audio):
        res = svc.detect_spikes(dummy_file, start_time=10.0, end_time=15.0)

    assert res["has_spike"] is True
    # Peak must be around 10.0 + 3.0s = ~13.0s
    assert 12.7 <= res["peak_time"] <= 13.3
    assert res["peak_db"] > res["mean_db"] + 6.0


def test_get_hook_window_from_spike():
    svc = AudioSpikeDetectorService()
    # Spike di detik 25.0 dalam window [10.0, 40.0]
    start, end = svc.get_hook_window_from_spike(
        peak_time=25.0,
        window_start=10.0,
        window_end=40.0,
        teaser_duration=2.5,
    )
    # Harus mulai ~0.75s sebelum peak: 25.0 - 0.75 = 24.25
    assert start == pytest.approx(24.25, abs=0.1)
    assert end == pytest.approx(26.75, abs=0.1)
