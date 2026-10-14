"""Unit tests for SilenceStripperService."""

from unittest.mock import MagicMock, patch
import pytest

from app.core.exceptions.base import NotFoundException, ValidationException
from app.services.silence_stripper_service import SilenceStripperService


def _make_service(metadata=None):
    mock_db = MagicMock()
    clip = MagicMock()
    clip.id = 12
    clip.file_path = "data/outputs/clip_12.mp4"
    clip.edited_file_path = None
    clip.start_time = 0.0
    clip.end_time = 60.0

    repo = MagicMock()
    repo.get.return_value = clip

    ffmpeg = MagicMock()
    ffmpeg.extract_metadata.return_value = metadata or {"duration_seconds": 60.0, "width": 1080, "height": 1920}
    ffmpeg.ffmpeg_path = "ffmpeg"

    service = SilenceStripperService(mock_db)
    service.clip_repo = repo
    service.ffmpeg = ffmpeg
    return service, clip


def test_detect_active_intervals_with_gaps() -> None:
    """When speech segments have gaps > min_silence_duration, active intervals should be returned."""
    service, clip = _make_service()

    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("app.ai_modules.speech_to_text.whisper_analyzer.WhisperAnalyzer.analyze") as mock_whisper:

        mock_run.return_value = MagicMock(returncode=0)
        # Mock 2 speech intervals with a 15-second silence gap in between (0-10 and 25-40)
        mock_whisper.return_value = MagicMock(
            result_data={
                "segments": [
                    {"start": 0.0, "end": 10.0, "text": "halo semua"},
                    {"start": 25.0, "end": 40.0, "text": "lanjut main game"},
                ]
            }
        )

        res = service.detect_active_intervals(clip.file_path, min_silence_duration=1.5, padding=0.25)

        assert res["total_duration"] == 60.0
        assert len(res["active_intervals"]) == 2
        # First interval ~0.0 to 10.25, second ~24.75 to 40.25
        assert res["active_intervals"][0][0] == 0.0
        assert res["active_intervals"][0][1] == 10.25
        assert res["active_intervals"][1][0] == 24.75
        assert res["active_intervals"][1][1] == 40.25
        assert res["removed_duration"] > 10.0


def test_detect_active_intervals_no_silence() -> None:
    """When speech is continuous without gaps > min_silence_duration, 0 duration is removed."""
    service, clip = _make_service()

    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("app.ai_modules.speech_to_text.whisper_analyzer.WhisperAnalyzer.analyze") as mock_whisper:

        mock_run.return_value = MagicMock(returncode=0)
        mock_whisper.return_value = MagicMock(
            result_data={
                "segments": [
                    {"start": 0.0, "end": 29.5, "text": "bicara terus"},
                    {"start": 30.0, "end": 60.0, "text": "sampai selesai"},
                ]
            }
        )

        res = service.detect_active_intervals(clip.file_path, min_silence_duration=1.5, padding=0.25)
        # Only 1 merged interval because 0.5s gap < 1.5s threshold
        assert len(res["active_intervals"]) == 1
        assert res["removed_duration"] == 0.0


def test_strip_silence_success() -> None:
    """strip_silence should render trimmed concat video and push edit history."""
    service, clip = _make_service()

    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("app.services.silence_stripper_service.SilenceStripperService.detect_active_intervals") as mock_detect, \
         patch("app.services.clip_history_manager.ClipHistoryManager.push_step") as mock_push:

        mock_run.return_value = MagicMock(returncode=0)
        mock_detect.return_value = {
            "active_intervals": [(0.0, 10.0), (25.0, 45.0)],
            "total_duration": 60.0,
            "new_duration": 30.0,
            "removed_duration": 30.0,
            "gaps_count": 1,
        }

        updated = service.strip_silence(12, min_silence_duration=1.5, padding=0.25)

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "concat=n=2:v=1:a=1" in "".join(cmd)
        assert mock_push.called
        assert updated.end_time == 30.0


def test_strip_silence_validation_no_gaps() -> None:
    """strip_silence raises ValidationException if video has no significant silence."""
    service, clip = _make_service()

    with patch("pathlib.Path.exists", return_value=True), \
         patch("app.services.silence_stripper_service.SilenceStripperService.detect_active_intervals") as mock_detect:

        mock_detect.return_value = {
            "active_intervals": [(0.0, 60.0)],
            "total_duration": 60.0,
            "new_duration": 60.0,
            "removed_duration": 0.0,
            "gaps_count": 0,
        }

        with pytest.raises(ValidationException, match="Tidak ditemukan jeda hening"):
            service.strip_silence(12)
