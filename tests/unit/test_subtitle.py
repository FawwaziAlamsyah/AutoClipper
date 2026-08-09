"""Tests for SubtitleService."""

from unittest.mock import MagicMock

from app.models.transcript_segment_model import TranscriptSegment
from app.services.subtitle_service import SubtitleService


def _make_service(segments_texts: list[tuple[float, float, str]]) -> SubtitleService:
    mock_db = MagicMock()
    mock_segments = [
        TranscriptSegment(id=i + 1, start_time=st, end_time=et, text=text, confidence=0.9)
        for i, (st, et, text) in enumerate(segments_texts)
    ]
    mock_transcript = MagicMock()
    mock_transcript.segments = mock_segments
    mock_transcript.job_id = 1

    mock_clip = MagicMock()
    mock_clip.id = 1
    mock_clip.job_id = 1
    mock_clip.start_time = 0.0
    mock_clip.end_time = 20.0

    service = SubtitleService(mock_db)
    service.transcript_repo = MagicMock()
    service.clip_repo = MagicMock()
    service.transcript_repo.get_by_job.return_value = mock_transcript
    service.clip_repo.get.return_value = mock_clip
    return service


def test_generate_srt_word_level() -> None:
    """Subtitle should split segments into word-level cues."""
    service = _make_service([(0.0, 6.0, "Halo dunia ini contoh")])
    result = service.generate_subtitle(1, "srt", "id")

    assert result["format"] == "srt"
    assert result["lines"] == 1
    assert "Halo dunia ini contoh" in result["content"]
    assert "-->" in result["content"]


def test_generate_vtt_tiktok_style() -> None:
    """TikTok style should uppercase text."""
    service = _make_service([(0.0, 2.0, "wow amazing")])
    result = service.generate_subtitle(1, "vtt", "id", style="tiktok")

    assert result["style"] == "tiktok"
    assert result["content"].startswith("WEBVTT")
    assert "WOW AMAZING" in result["content"]


def test_style_fallback_to_minimal() -> None:
    """Unknown style should fall back to minimal."""
    service = _make_service([(0.0, 2.0, "hello world")])
    result = service.generate_subtitle(1, "srt", "id", style="nope")
    assert result["style"] == "minimal"
