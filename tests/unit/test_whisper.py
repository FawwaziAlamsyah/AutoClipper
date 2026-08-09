"""Tests for WhisperAnalyzer plugin using mock."""

from unittest.mock import MagicMock, patch

from app.ai_modules.speech_to_text.whisper_analyzer import WhisperAnalyzer


@patch("app.ai_modules.speech_to_text.whisper_analyzer.WhisperModel")
def test_whisper_analyze_success(mock_whisper_class: MagicMock) -> None:
    """WhisperAnalyzer should parse faster-whisper output correctly."""
    # Setup mock whisper instance and returned values
    mock_instance = mock_whisper_class.return_value

    mock_word = MagicMock()
    mock_word.word = "Halo"
    mock_word.start = 0.0
    mock_word.end = 0.5
    mock_word.probability = 0.99

    mock_segment = MagicMock()
    mock_segment.text = "Halo dunia"
    mock_segment.start = 0.0
    mock_segment.end = 1.0
    mock_segment.words = [mock_word]

    # Model.transcribe returns (generator/list of segments, info)
    mock_info = MagicMock()
    mock_info.language = "id"

    mock_instance.transcribe.return_value = ([mock_segment], mock_info)

    with patch("pathlib.Path.exists", return_value=True):
        analyzer = WhisperAnalyzer()
        result = analyzer.analyze({"audio_path": "dummy.wav"})
        data = result.result_data

        assert result.score == 5.0
        assert data["language"] == "id"
        assert data["full_text"] == "Halo dunia"
        assert len(data["segments"]) == 1

        seg = data["segments"][0]
        assert seg["text"] == "Halo dunia"
        assert seg["start"] == 0.0
        assert seg["end"] == 1.0
        assert len(seg["words"]) == 1
        assert seg["words"][0]["word"] == "Halo"
