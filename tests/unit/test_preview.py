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


def test_build_candidate_thumbnail_file(tmp_path) -> None:
    """PreviewService should extract thumbnail at appropriate timestamp."""
    mock_db = MagicMock()
    service = PreviewService(mock_db)

    candidate = MagicMock()
    candidate.id = 1
    candidate.video_id = 2
    candidate.start_time = 10.0
    candidate.end_time = 40.0

    video_file = tmp_path / "video.mp4"
    video_file.write_text("mock video content")

    video = MagicMock()
    video.id = 2
    video.file_path = str(video_file)
    video.is_archived = False

    service.candidate_repo = MagicMock()
    service.video_repo = MagicMock()
    service.candidate_repo.get.return_value = candidate
    service.video_repo.get.return_value = video

    service.ffmpeg_service = MagicMock()
    service.ffmpeg_service.extract_thumbnail.return_value = "thumb.jpg"

    res = service.build_candidate_thumbnail_file(1, "thumb.jpg")
    assert res == "thumb.jpg"
    service.ffmpeg_service.extract_thumbnail.assert_called_once_with(
        str(video_file), "thumb.jpg", timestamp=11.0
    )


def test_build_video_thumbnail_file(tmp_path) -> None:
    """PreviewService should extract video thumbnail."""
    mock_db = MagicMock()
    service = PreviewService(mock_db)

    video_file = tmp_path / "video.mp4"
    video_file.write_text("mock video content")

    video = MagicMock()
    video.id = 2
    video.file_path = str(video_file)
    video.duration_seconds = 60.0

    service.video_repo = MagicMock()
    service.video_repo.get.return_value = video

    service.ffmpeg_service = MagicMock()
    service.ffmpeg_service.extract_thumbnail.return_value = "video_thumb.jpg"

    res = service.build_video_thumbnail_file(2, "video_thumb.jpg")
    assert res == "video_thumb.jpg"
    service.ffmpeg_service.extract_thumbnail.assert_called_once_with(
        str(video_file), "video_thumb.jpg", timestamp=3.0
    )


