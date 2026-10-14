"""Tests for SubtitleService."""

from unittest.mock import MagicMock

from app.models.transcript_segment_model import TranscriptSegmentModel
from app.services.subtitle_service import SubtitleService


def _make_service(segments_texts: list[tuple[float, float, str]]) -> SubtitleService:
    mock_db = MagicMock()
    mock_segments = [
        TranscriptSegmentModel(id=i + 1, start_time=st, end_time=et, text=text, confidence=0.9)
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
    mock_clip.aspect_ratio = "9:16"

    service = SubtitleService(mock_db)
    service.transcript_repo = MagicMock()
    service.clip_repo = MagicMock()
    service.transcript_repo.get_by_job.return_value = mock_transcript
    service.clip_repo.get.return_value = mock_clip
    # JobService tak diuji di sini — mock agar ensure/start/finish step no-op
    service.job_service = MagicMock()
    return service


def test_generate_srt_word_level() -> None:
    """Subtitle should split segments into word-level cues."""
    service = _make_service([(0.0, 6.0, "Halo dunia ini contoh")])
    result = service.generate_subtitle(1, "srt", "id", burn=False)

    assert result["format"] == "srt"
    assert result["lines"] == 1
    assert "Halo dunia ini contoh" in result["content"]
    assert "-->" in result["content"]


def test_generate_vtt_tiktok_style() -> None:
    """TikTok style should uppercase text."""
    service = _make_service([(0.0, 2.0, "wow amazing")])
    result = service.generate_subtitle(1, "vtt", "id", style="tiktok", burn=False)

    assert result["style"] == "tiktok"
    assert result["content"].startswith("WEBVTT")
    assert "WOW AMAZING" in result["content"]


def test_style_fallback_to_minimal() -> None:
    """Unknown style should fall back to minimal."""
    service = _make_service([(0.0, 2.0, "hello world")])
    result = service.generate_subtitle(1, "srt", "id", style="nope", burn=False)
    assert result["style"] == "minimal"


def test_generate_ass_tiktok_kinetic_style() -> None:
    """TikTok style with format ass should produce valid kinetic ASS script."""
    service = _make_service([(0.0, 4.0, "Waduh gila banget ini guys kaget parah")])
    result = service.generate_subtitle(1, "ass", "id", style="tiktok", burn=False, font_style="impact")

    assert result["format"] == "ass"
    assert result["style"] == "tiktok"
    assert "[Script Info]" in result["content"]
    assert "PlayResX: 1080" in result["content"]
    assert "PlayResY: 1920" in result["content"]
    assert "Style: TikTokKinetic,Anton" in result["content"]
    assert "\\pos(540,1286)" in result["content"]
    assert "\\fscx106" in result["content"]
    assert "&H00E6FF&" in result["content"]  # Yellow highlight


def test_segments_sorted_chronologically() -> None:
    """Segments that arrive out-of-order should be sorted chronologically."""
    # Given out of order segments (start at 5.0, then 1.0)
    service = _make_service([(5.0, 7.0, "segmen kedua"), (1.0, 3.0, "segmen pertama")])
    result = service.generate_subtitle(1, "ass", "id", style="tiktok", burn=False)
    lines = [line for line in result["content"].splitlines() if line.startswith("Dialogue:")]
    assert len(lines) >= 2
    # First dialogue should have earlier timestamp than second
    assert "0:00:01" in lines[0]


def test_noise_filtering_short_blip() -> None:
    """Ultra-short noise words (< 0.25s) should be ignored."""
    from app.models.transcript_segment_model import TranscriptSegmentModel
    service = _make_service([])
    seg_noise = TranscriptSegmentModel(id=1, start_time=1.0, end_time=1.1, text="keseh", confidence=0.3)
    seg_valid = TranscriptSegmentModel(id=2, start_time=2.0, end_time=4.0, text="halo semua", confidence=0.9)
    cues = service._build_kinetic_cues([seg_noise, seg_valid])
    assert all("KESEH" not in c["text"] for c in cues)


