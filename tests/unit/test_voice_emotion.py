"""Tests for VoiceEmotionAnalyzer using mock librosa."""

from unittest.mock import MagicMock, patch

import numpy as np

from app.ai_modules.voice_analysis.voice_emotion_analyzer import VoiceEmotionAnalyzer


@patch("app.ai_modules.voice_analysis.voice_emotion_analyzer.librosa")
def test_voice_emotion_analyze(mock_librosa: MagicMock) -> None:
    """Voice emotion returns score 0-10 with result_data."""
    sr = 16000
    y = np.random.randn(sr).astype(np.float32) * 0.1  # 1 detik noise

    mock_librosa.load.return_value = (y, sr)
    mock_librosa.feature.rms.return_value = np.full((1, 1), 0.1)
    mock_librosa.feature.zero_crossing_rate.return_value = np.full((1, 1), 0.05)
    mock_librosa.yin.return_value = np.full(1, 150.0)

    analyzer = VoiceEmotionAnalyzer()
    with patch("pathlib.Path.exists", return_value=True):
        result = analyzer.analyze({"audio_path": "dummy.wav", "start": 0, "end": 1})

    assert 0.0 <= result.score <= 10.0
    assert "reason" in result.result_data
    assert "avg_loudness_db" in result.result_data


@patch("app.ai_modules.voice_analysis.voice_emotion_analyzer.librosa")
def test_voice_emotion_missing_audio(mock_librosa: MagicMock) -> None:
    """Missing audio path → AnalyzerUnavailable."""
    from app.ai_modules.base.analyzer_interface import AnalyzerUnavailable

    analyzer = VoiceEmotionAnalyzer()
    with patch("pathlib.Path.exists", return_value=False):
        try:
            analyzer.analyze({"audio_path": "missing.wav", "start": 0, "end": 1})
            assert False, "should raise"
        except AnalyzerUnavailable:
            pass
