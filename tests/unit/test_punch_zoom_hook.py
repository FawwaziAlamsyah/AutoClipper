"""Unit tests for Feature 4: Emotion Punch-Zoom Hook Trigger & Audio Spike Retargeting."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.ai_modules.hook_analysis.hook_moment_finder import HookMoment
from app.services.hook_composer_service import HookComposerService
from app.services.clip_service import ClipService


def test_hook_composer_passes_punch_zoom_to_render():
    """compose() dan regenerate_from_candidate() meneruskan punch_zoom_scale dan zoom_target."""
    mock_db = MagicMock()
    mock_clip = MagicMock()
    mock_clip.id = 1

    mock_clip_repo = MagicMock()
    mock_clip_repo.get.return_value = mock_clip

    service = HookComposerService(mock_db)
    service.clip_repo = mock_clip_repo

    dummy_hook = HookMoment(
        hook_moment_start=30.0,
        hook_moment_end=32.5,
        hook_type="shock",
        hook_confidence=0.9,
        hook_caption="Kaget banget!",
        best_idx=3,
    )

    with patch.object(service, "_render_hook", return_value=Path("dummy_out.mp4")) as mock_render, \
         patch("app.services.clip_history_manager.ClipHistoryManager.get_base_for_hook", return_value=Path("dummy_base.mp4")), \
         patch("app.services.clip_history_manager.ClipHistoryManager.push_step"):

        # Test compose
        res = service.compose(
            clip_id=1,
            video_source_path="video.mp4",
            aspect_ratio="9:16",
            hook_moment=dummy_hook,
            window_duration=30.0,
            layout="stacked_split",
            punch_zoom_scale=1.35,
            zoom_target="facecam",
        )
        assert res is True
        mock_render.assert_called_once()
        _, kwargs = mock_render.call_args
        assert kwargs["punch_zoom_scale"] == 1.35
        assert kwargs["zoom_target"] == "facecam"

        # Test regenerate_from_candidate
        mock_render.reset_mock()
        res_regen = service.regenerate_from_candidate(
            clip_id=1,
            video_source_path="video.mp4",
            aspect_ratio="9:16",
            hook_moment=dummy_hook,
            window_duration=30.0,
            layout="stacked_split",
            punch_zoom_scale=1.15,
            zoom_target="full",
        )
        assert res_regen is True
        mock_render.assert_called_once()
        _, kwargs = mock_render.call_args
        assert kwargs["punch_zoom_scale"] == 1.15
        assert kwargs["zoom_target"] == "full"


def test_apply_zoom_punch_passthrough_on_split_facecam(tmp_path):
    """Pada layout stacked_split dan target facecam, _apply_zoom_punch menyalin file secara langsung tanpa seam cut."""
    mock_db = MagicMock()
    service = HookComposerService(mock_db)

    in_file = tmp_path / "in.mp4"
    in_file.write_text("dummy video content")
    out_file = tmp_path / "out.mp4"

    service._apply_zoom_punch(
        source=str(in_file),
        output=str(out_file),
        aspect_ratio="9:16",
        punch_zoom_scale=1.35,
        zoom_target="facecam",
        layout="stacked_split",
    )

    assert out_file.exists()
    assert out_file.read_text() == "dummy video content"


def test_apply_zoom_punch_runs_ffmpeg_on_full_target(tmp_path):
    """Pada target full frame atau layout non-split, _apply_zoom_punch menjalankan crop FFmpeg."""
    mock_db = MagicMock()
    service = HookComposerService(mock_db)

    in_file = tmp_path / "in.mp4"
    in_file.write_text("dummy")
    out_file = tmp_path / "out.mp4"

    with patch.object(service, "_run") as mock_run:
        service._apply_zoom_punch(
            source=str(in_file),
            output=str(out_file),
            aspect_ratio="9:16",
            punch_zoom_scale=1.25,
            zoom_target="full",
            layout="stacked_split",
        )
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Pastikan ada crop dan scale
        filter_str = [cmd[i+1] for i, arg in enumerate(cmd) if arg == "-vf"][0]
        assert "crop=" in filter_str
        assert "scale=1080:1920" in filter_str


def test_clip_service_snap_hook_to_audio_spike():
    """ClipService.snap_hook_to_audio_spike mendeteksi spike dan mengupdate hook_moment_start/end."""
    mock_db = MagicMock()
    service = ClipService(mock_db)

    mock_clip = MagicMock()
    mock_clip.id = 10
    mock_clip.candidate_id = 100
    mock_clip.start_time = 0.0
    mock_clip.end_time = 30.0

    mock_candidate = MagicMock()
    mock_candidate.id = 100
    mock_candidate.video_id = 500
    mock_candidate.start_time = 0.0
    mock_candidate.end_time = 30.0
    mock_candidate.score_breakdown = {}

    mock_video = MagicMock()
    mock_video.file_path = "video.mp4"

    service.clip_repo = MagicMock()
    service.clip_repo.get.return_value = mock_clip

    service.candidate_repo = MagicMock()
    service.candidate_repo.get.return_value = mock_candidate

    service.video_repo = MagicMock()
    service.video_repo.get.return_value = mock_video

    dummy_spikes = {
        "has_spike": True,
        "peak_time": 22.0,
        "peak_rel_time": 22.0,
        "peak_db": -4.0,
        "mean_db": -24.0,
    }

    with patch("pathlib.Path.exists", return_value=True), \
         patch("app.services.audio_spike_detector_service.AudioSpikeDetectorService.detect_spikes", return_value=dummy_spikes), \
         patch.object(service, "regenerate_hook", return_value=mock_clip) as mock_regen:

        res = service.snap_hook_to_audio_spike(10, punch_zoom_scale=1.35, zoom_target="facecam")

        assert res == mock_clip
        # Peak 22.0s -> ideal start 22.0 - 0.75 = 21.25s
        assert mock_candidate.hook_moment_start == pytest.approx(21.25, abs=0.1)
        assert mock_candidate.hook_moment_end == pytest.approx(23.75, abs=0.1)
        assert mock_candidate.hook_type == "shock"
        mock_regen.assert_called_once_with(10, punch_zoom_scale=1.35, zoom_target="facecam")
