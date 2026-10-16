"""Unit tests untuk InstagramVideoPrepService (kalkulasi rasio 9:16, pad, blur, bypass, cleanup, timeout)."""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions.base import ValidationException
from app.services.ffmpeg_service import FFmpegService
from app.services.instagram_video_prep_service import (
    InstagramVideoPrepService,
    PreparedVideo,
)


@pytest.fixture
def dummy_video(tmp_path: Path) -> Path:
    video_file = tmp_path / "sample_test.mp4"
    video_file.write_bytes(b"dummy mp4 video bytes" * 50)
    return video_file


class TestInstagramVideoPrepNeedsReframe:
    def test_exact_9_16_returns_false(self):
        svc = InstagramVideoPrepService()
        assert svc.needs_reframe(1080, 1920) is False
        assert svc.needs_reframe(720, 1280) is False
        assert svc.needs_reframe(2160, 3840) is False

    def test_within_one_percent_tolerance_returns_false(self):
        svc = InstagramVideoPrepService()
        # 1080 / 1920 = 0.5625
        # 0.5625 * 1.005 = ~0.5653 => 1085 / 1920 = 0.5651 (within 1%)
        assert svc.needs_reframe(1085, 1920) is False
        # 0.5625 * 0.995 = ~0.5596 => 1075 / 1920 = 0.5598 (within 1%)
        assert svc.needs_reframe(1075, 1920) is False

    def test_horizontal_16_9_returns_true(self):
        svc = InstagramVideoPrepService()
        assert svc.needs_reframe(1920, 1080) is True
        assert svc.needs_reframe(1280, 720) is True

    def test_square_1_1_returns_true(self):
        svc = InstagramVideoPrepService()
        assert svc.needs_reframe(1080, 1080) is True

    def test_invalid_dimensions_returns_false(self):
        svc = InstagramVideoPrepService()
        assert svc.needs_reframe(0, 1920) is False
        assert svc.needs_reframe(1080, 0) is False
        assert svc.needs_reframe(-100, 100) is False


class TestInstagramVideoPrepPrepare:
    def test_prepare_mode_off_returns_original(self, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        prep = svc.prepare(dummy_video, fit_mode="off")
        assert prep.path == dummy_video
        assert prep.is_temp is False
        assert prep.reframed is False

    @patch("subprocess.run")
    def test_prepare_already_9_16_bypasses_ffmpeg(self, mock_subproc, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        mock_ffmpeg.extract_metadata.return_value = {
            "duration_seconds": 15.0,
            "width": 1080,
            "height": 1920,
            "rotation": 0,
            "fps": 30.0,
        }
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        prep = svc.prepare(dummy_video, fit_mode="pad")
        assert prep.path == dummy_video
        assert prep.is_temp is False
        assert prep.reframed is False
        assert prep.width == 1080
        assert prep.height == 1920
        mock_subproc.assert_not_called()

    @patch("subprocess.run")
    def test_prepare_rotation_90_bypasses_when_display_is_9_16(self, mock_subproc, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        # Raw storage is 1920x1080, but rotation=90 swaps display to 1080x1920
        mock_ffmpeg.extract_metadata.return_value = {
            "duration_seconds": 15.0,
            "width": 1920,
            "height": 1080,
            "rotation": 90,
            "fps": 30.0,
        }
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        prep = svc.prepare(dummy_video, fit_mode="pad")
        assert prep.path == dummy_video
        assert prep.is_temp is False
        assert prep.reframed is False
        mock_subproc.assert_not_called()

    @patch("subprocess.run")
    def test_prepare_pad_mode_runs_ffmpeg(self, mock_subproc, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        mock_ffmpeg.ffmpeg_path = "ffmpeg"
        mock_ffmpeg.extract_metadata.return_value = {
            "duration_seconds": 20.0,
            "width": 1920,
            "height": 1080,
            "rotation": 0,
            "fps": 60.0,  # Should cap fps to 30
        }
        mock_subproc.return_value = MagicMock(returncode=0, stderr="")
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        prep = svc.prepare(dummy_video, fit_mode="pad")

        assert prep.is_temp is True
        assert prep.reframed is True
        assert prep.width == 1080
        assert prep.height == 1920
        assert "ig_fit_" in str(prep.path.parent)

        # Verifikasi command ffmpeg dipanggil dengan argumen yang benar
        mock_subproc.assert_called_once()
        cmd_args = mock_subproc.call_args[0][0]
        assert "-vf" in cmd_args
        vf_idx = cmd_args.index("-vf")
        filter_str = cmd_args[vf_idx + 1]
        assert "scale=1080:1920:force_original_aspect_ratio=decrease" in filter_str
        assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black" in filter_str
        assert ",fps=30" in filter_str

        # Cleanup temp file
        svc.cleanup(prep)
        assert not prep.path.exists()
        assert not prep.path.parent.exists()

    @patch("subprocess.run")
    def test_prepare_blur_mode_runs_ffmpeg_with_filter_complex(self, mock_subproc, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        mock_ffmpeg.ffmpeg_path = "ffmpeg"
        mock_ffmpeg.extract_metadata.return_value = {
            "duration_seconds": 12.0,
            "width": 1920,
            "height": 1080,
            "rotation": 0,
            "fps": 25.0,  # fps <= 30 so no fps cap filter
        }
        mock_subproc.return_value = MagicMock(returncode=0, stderr="")
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        prep = svc.prepare(dummy_video, fit_mode="blur")

        assert prep.is_temp is True
        assert prep.reframed is True
        mock_subproc.assert_called_once()
        cmd_args = mock_subproc.call_args[0][0]
        assert "-filter_complex" in cmd_args
        fc_idx = cmd_args.index("-filter_complex")
        filter_str = cmd_args[fc_idx + 1]
        assert "boxblur=20:5" in filter_str
        assert "overlay=(W-w)/2:(H-h)/2" in filter_str

        svc.cleanup(prep)
        assert not prep.path.parent.exists()

    @patch("subprocess.run")
    def test_prepare_ffmpeg_failure_cleans_up_temp_and_raises(self, mock_subproc, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        mock_ffmpeg.ffmpeg_path = "ffmpeg"
        mock_ffmpeg.extract_metadata.return_value = {
            "duration_seconds": 10.0,
            "width": 1920,
            "height": 1080,
            "rotation": 0,
        }
        mock_subproc.return_value = MagicMock(returncode=1, stderr="Invalid filter parameters")
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        with pytest.raises(ValidationException) as exc_info:
            svc.prepare(dummy_video, fit_mode="pad")

        assert "Gagal menyiapkan video 9:16" in str(exc_info.value)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=900))
    def test_prepare_ffmpeg_timeout_cleans_up_temp_and_raises(self, mock_subproc, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        mock_ffmpeg.ffmpeg_path = "ffmpeg"
        mock_ffmpeg.extract_metadata.return_value = {
            "duration_seconds": 10.0,
            "width": 1920,
            "height": 1080,
            "rotation": 0,
        }
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        with pytest.raises(ValidationException) as exc_info:
            svc.prepare(dummy_video, fit_mode="pad")

        assert "Timeout" in str(exc_info.value)

    def test_prepare_nonexistent_file_raises_validation_exception(self, tmp_path: Path):
        svc = InstagramVideoPrepService()
        missing = tmp_path / "not_there.mp4"
        with pytest.raises(ValidationException) as exc_info:
            svc.prepare(missing)
        assert "tidak ditemukan di disk" in str(exc_info.value)


class TestInstagramVideoPrepCleanup:
    def test_cleanup_non_temp_does_not_delete(self, dummy_video: Path):
        svc = InstagramVideoPrepService()
        prep = PreparedVideo(path=dummy_video, is_temp=False, reframed=False)
        svc.cleanup(prep)
        assert dummy_video.exists()

    def test_cleanup_none_safe_noop(self):
        svc = InstagramVideoPrepService()
        svc.cleanup(None)  # Should not raise


class TestInstagramVideoPrepNeedsTranscode:
    def test_yuv420p_h264_square_sar_returns_false(self):
        svc = InstagramVideoPrepService()
        meta = {
            "pix_fmt": "yuv420p",
            "video_codec": "h264",
            "profile": "High",
            "sample_aspect_ratio": "1:1",
        }
        assert svc.needs_transcode(meta) is False

    def test_yuv444p_returns_true(self):
        svc = InstagramVideoPrepService()
        meta = {
            "pix_fmt": "yuv444p",
            "video_codec": "h264",
            "profile": "High 4:4:4 Predictive",
        }
        assert svc.needs_transcode(meta) is True

    def test_profile_444_returns_true(self):
        svc = InstagramVideoPrepService()
        meta = {
            "profile": "High 4:4:4 Predictive",
        }
        assert svc.needs_transcode(meta) is True

    def test_hevc_codec_returns_true(self):
        svc = InstagramVideoPrepService()
        meta = {
            "pix_fmt": "yuv420p",
            "video_codec": "hevc",
        }
        assert svc.needs_transcode(meta) is True

    def test_non_square_sar_returns_true(self):
        svc = InstagramVideoPrepService()
        meta = {
            "pix_fmt": "yuv420p",
            "video_codec": "h264",
            "sample_aspect_ratio": "1150:1107",
        }
        assert svc.needs_transcode(meta) is True

    @patch("subprocess.run")
    def test_prepare_already_9_16_but_yuv444p_triggers_transcode(self, mock_subproc, dummy_video: Path):
        mock_ffmpeg = MagicMock(spec=FFmpegService)
        mock_ffmpeg.ffmpeg_path = "ffmpeg"
        mock_ffmpeg.extract_metadata.return_value = {
            "duration_seconds": 15.0,
            "width": 1080,
            "height": 1920,
            "rotation": 0,
            "fps": 30.0,
            "pix_fmt": "yuv444p",
            "profile": "High 4:4:4 Predictive",
            "sample_aspect_ratio": "1150:1107",
        }
        mock_subproc.return_value = MagicMock(returncode=0, stderr="")
        svc = InstagramVideoPrepService(ffmpeg_service=mock_ffmpeg)

        prep = svc.prepare(dummy_video, fit_mode="pad")
        assert prep.is_temp is True
        assert prep.reframed is True
        mock_subproc.assert_called_once()
        cmd_args = mock_subproc.call_args[0][0]
        assert "-pix_fmt" in cmd_args
        assert cmd_args[cmd_args.index("-pix_fmt") + 1] == "yuv420p"

        svc.cleanup(prep)
