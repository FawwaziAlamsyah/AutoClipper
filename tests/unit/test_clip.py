"""Tests for ClipService."""

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from app.models.clip_model import ClipModel
from app.services.clip_service import ClipService


def test_generate_clip_success() -> None:
    """ClipService should persist clip record."""
    mock_db = MagicMock()

    mock_candidate = MagicMock()
    mock_candidate.id = 1
    mock_candidate.video_id = 1
    mock_candidate.job_id = 1
    mock_candidate.start_time = 10.0
    mock_candidate.end_time = 45.0
    mock_candidate.status = "selected"

    mock_clip = ClipModel(
        id=99,
        video_id=1,
        candidate_id=1,
        file_path="C:/output/clip_1.mp4",
        start_time=10.0,
        end_time=45.0,
        aspect_ratio="9:16",
        has_subtitle=False,
        status="completed",
        created_at=datetime.now(UTC),
    )

    mock_video = MagicMock()
    mock_video.id = 1
    mock_video.file_path = "C:/input/video.mp4"
    mock_video.is_archived = False

    mock_repo = MagicMock()
    mock_repo.get.return_value = mock_candidate
    mock_repo.add.return_value = mock_clip

    mock_video_repo = MagicMock()
    mock_video_repo.get.return_value = mock_video

    completed = MagicMock()
    completed.returncode = 0
    completed.stderr = ""

    with patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("app.services.clip_service.subprocess.run", return_value=completed):
        service = ClipService(mock_db)
        service.clip_repo = mock_repo
        service.candidate_repo = mock_repo
        service.video_repo = mock_video_repo
        service.job_service = MagicMock()

        clip = service.generate_clip(1, "9:16", subtitle_enabled=False, subtitle_style="minimal")

    assert clip.id == 99
    assert clip.status == "completed"
    assert clip.aspect_ratio == "9:16"
