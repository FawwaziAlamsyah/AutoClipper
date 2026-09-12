"""Tests for ClipEditorService.crop_frame (spatial crop, bukan trim waktu)."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions.base import NotFoundException, ValidationException
from app.services.clip_editor_service import ClipEditorService


def _make_service(metadata=None):
    mock_db = MagicMock()
    clip = MagicMock()
    clip.id = 7
    clip.file_path = "C:/data/outputs/clip_7.mp4"
    clip.edited_file_path = None
    clip.start_time = 0.0
    clip.end_time = 10.0

    repo = MagicMock()
    repo.get.return_value = clip

    ffmpeg = MagicMock()
    ffmpeg.extract_metadata.return_value = metadata or {"width": 1920, "height": 1080}

    service = ClipEditorService(mock_db)
    service.clip_repo = repo
    service.ffmpeg = ffmpeg
    return service, clip


def test_crop_frame_success() -> None:
    """Crop area di dalam batas → ffmpeg crop=w:h:x:y, edited_file_path update."""
    service, clip = _make_service()

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.unlink"), \
         patch("pathlib.Path.rename"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = service.crop_frame(7, 100, 50, 800, 600)

    called = mock_run.call_args[0][0]
    assert "-vf" in called
    assert called[called.index("-vf") + 1] == "crop=800:600:100:50"
    assert result is clip


def test_crop_frame_validation_out_of_bounds() -> None:
    """x+width melebihi lebar video → ValidationException dengan pesan jelas."""
    service, _ = _make_service()

    with patch("pathlib.Path.exists", return_value=True):
        with pytest.raises(ValidationException, match="melampaui lebar"):
            service.crop_frame(7, 1500, 50, 800, 600)


def test_crop_frame_validation_height() -> None:
    """y+height melebihi tinggi video → ValidationException."""
    service, _ = _make_service()

    with patch("pathlib.Path.exists", return_value=True):
        with pytest.raises(ValidationException, match="melampaui tinggi"):
            service.crop_frame(7, 10, 900, 800, 600)


def test_crop_frame_validation_negative() -> None:
    """x/y negatif atau width/height ≤ 0 → ValidationException."""
    service, _ = _make_service()

    with pytest.raises(ValidationException):
        service.crop_frame(7, -5, 0, 800, 600)
    with pytest.raises(ValidationException):
        service.crop_frame(7, 0, 0, 0, 600)


def test_crop_frame_not_found() -> None:
    """Clip tidak ada → NotFoundException."""
    service, _ = _make_service()
    service.clip_repo.get.return_value = None

    with pytest.raises(NotFoundException):
        service.crop_frame(999, 0, 0, 100, 100)