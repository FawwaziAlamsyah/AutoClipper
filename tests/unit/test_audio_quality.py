"""Tests for AudioQualityAnalyzer using mock librosa."""

from unittest.mock import MagicMock, patch

import numpy as np

from app.ai_modules.voice_analysis.audio_quality_analyzer import AudioQualityAnalyzer


@patch("app.ai_modules.voice_analysis.audio_quality_analyzer.librosa")
def test_audio_quality_analyze(mock_librosa: MagicMock) -> None:
    """Audio quality returns score 0-10 with SNR data."""
    sr = 16000
    y = np.random.randn(sr).astype(np.float32) * 0.05  # quiet, low noise

    mock_librosa.load.return_value = (y, sr)
    mock_librosa.feature.spectral_flatness.return_value = np.array([[0.2, 0.25]])

    analyzer = AudioQualityAnalyzer()
    with patch("pathlib.Path.exists", return_value=True):
        result = analyzer.analyze({"audio_path": "dummy.wav", "start": 0, "end": 1})

    assert 0.0 <= result.score <= 10.0
    assert "snr_db" in result.result_data
    assert "clipping_ratio" in result.result_data


@patch("app.ai_modules.voice_analysis.audio_quality_analyzer.librosa")
def test_audio_quality_clipping_penalty(mock_librosa: MagicMock) -> None:
    """Heavy clipping → score lower (penalty)."""
    sr = 16000
    y = np.full(sr, 1.0, dtype=np.float32)  # seluruhnya clipping (amplitudo penuh)
    y[::2] = -1.0

    mock_librosa.load.return_value = (y, sr)
    mock_librosa.feature.spectral_flatness.return_value = np.array([[0.5, 0.5]])

    analyzer = AudioQualityAnalyzer()
    with patch("pathlib.Path.exists", return_value=True):
        result = analyzer.analyze({"audio_path": "dummy.wav", "start": 0, "end": 1})

    assert 0.0 <= result.score <= 10.0
    assert result.result_data["clipping_ratio"] > 0.5
