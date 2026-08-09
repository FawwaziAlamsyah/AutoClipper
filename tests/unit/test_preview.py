"""Tests for PreviewService."""

from unittest.mock import MagicMock

from app.services.preview_service import PreviewService


def test_get_candidate_preview() -> None:
    """PreviewService should return timestamp preview payload."""
    mock_db = MagicMock()
    service = PreviewService(mock_db)

    candidate = MagicMock()
    candidate.id = 1
    candidate.video_id = 2
    candidate.start_time = 10.0
    candidate.end_time = 40.0
    candidate.final_score = 88.0
    candidate.hook_text = "strong hook"

    video = MagicMock()
    video.id = 2
    video.file_path = "data/uploads/video.mp4"

    service.candidate_repo = MagicMock()
    service.video_repo = MagicMock()
    service.candidate_repo.get.return_value = candidate
    service.video_repo.get.return_value = video

    preview = service.get_candidate_preview(1)

    assert preview["candidate_id"] == 1
    assert preview["video_id"] == 2
    assert preview["start_time"] == 10.0
    assert preview["end_time"] == 40.0
    assert preview["duration"] == 30.0
    assert preview["score"] == 88.0
