"""Tests for ClipService."""

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest

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


# ── Auto Hook Engine tests ────────────────────────────────────────────────────

def _make_service_with_mocks(start=10.0, end=70.0):
    """Helper: ClipService dengan semua deps di-mock."""
    mock_db = MagicMock()

    mock_candidate = MagicMock()
    mock_candidate.id = 1
    mock_candidate.video_id = 1
    mock_candidate.job_id = 1
    mock_candidate.start_time = start
    mock_candidate.end_time = end
    mock_candidate.status = "candidate"
    mock_candidate.category = None

    mock_video = MagicMock()
    mock_video.id = 1
    mock_video.file_path = "C:/input/video.mp4"
    mock_video.is_archived = False

    mock_clip = ClipModel(
        id=99, video_id=1, candidate_id=1,
        file_path="C:/output/clip_1.mp4",
        start_time=start, end_time=end,
        aspect_ratio="9:16", has_subtitle=False,
        status="completed", created_at=datetime.now(UTC),
    )

    mock_cand_repo = MagicMock()
    mock_cand_repo.get.return_value = mock_candidate

    mock_video_repo = MagicMock()
    mock_video_repo.get.return_value = mock_video

    mock_clip_repo = MagicMock()
    mock_clip_repo.add.return_value = mock_clip

    mock_transcript_repo = MagicMock()
    mock_transcript_repo.get_by_video.return_value = None  # default: no transcript

    mock_segment_repo = MagicMock()
    mock_segment_repo.get_by_transcript.return_value = []

    completed = MagicMock()
    completed.returncode = 0
    completed.stderr = ""

    return (
        mock_db, mock_candidate, mock_video, mock_clip,
        mock_cand_repo, mock_video_repo, mock_clip_repo,
        mock_transcript_repo, mock_segment_repo, completed,
    )


def _build_service(mock_db, mock_cand_repo, mock_video_repo, mock_clip_repo,
                   mock_transcript_repo, mock_segment_repo):
    service = ClipService(mock_db)
    service.candidate_repo = mock_cand_repo
    service.video_repo = mock_video_repo
    service.clip_repo = mock_clip_repo
    service.transcript_repo = mock_transcript_repo
    service.segment_repo = mock_segment_repo
    service.job_service = MagicMock()
    service.history_service = MagicMock()
    return service


def test_generate_clip_hook_disabled_behavior_identical() -> None:
    """Regression: USE_AUTO_HOOK=False → clip identik dengan versi sebelum fitur hook ada."""
    (mock_db, mock_candidate, mock_video, mock_clip,
     mock_cand_repo, mock_video_repo, mock_clip_repo,
     mock_transcript_repo, mock_segment_repo, completed) = _make_service_with_mocks()

    mock_settings = MagicMock()
    mock_settings.USE_AUTO_HOOK = False

    with patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("app.services.clip_service.subprocess.run", return_value=completed), \
         patch("app.services.clip_service.settings", mock_settings):

        service = _build_service(
            mock_db, mock_cand_repo, mock_video_repo, mock_clip_repo,
            mock_transcript_repo, mock_segment_repo,
        )
        clip = service.generate_clip(1, "9:16")

    assert clip.id == 99
    assert clip.status == "completed"
    # hook engine tidak dipanggil sama sekali
    mock_transcript_repo.get_by_video.assert_not_called()


def test_generate_clip_hook_skip_no_transcript() -> None:
    """USE_AUTO_HOOK=True tapi tidak ada transcript → clip tetap berhasil, hook_skip_reason diset."""
    (mock_db, mock_candidate, mock_video, mock_clip,
     mock_cand_repo, mock_video_repo, mock_clip_repo,
     mock_transcript_repo, mock_segment_repo, completed) = _make_service_with_mocks()

    mock_settings = MagicMock()
    mock_settings.USE_AUTO_HOOK = True
    mock_settings.AUTO_HOOK_MIN_CONFIDENCE = 0.6
    mock_settings.AUTO_HOOK_MIN_WINDOW_SECONDS = 20.0

    mock_transcript_repo.get_by_video.return_value = None  # no transcript

    with patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("app.services.clip_service.subprocess.run", return_value=completed), \
         patch("app.services.clip_service.settings", mock_settings):

        service = _build_service(
            mock_db, mock_cand_repo, mock_video_repo, mock_clip_repo,
            mock_transcript_repo, mock_segment_repo,
        )
        clip = service.generate_clip(1, "9:16")

    # Clip tetap sukses
    assert clip.id == 99
    assert clip.status == "completed"


def test_generate_clip_hook_engine_exception_does_not_fail_clip() -> None:
    """HookMomentFinder raise exception → clip tetap tersimpan, tidak propagate error."""
    (mock_db, mock_candidate, mock_video, mock_clip,
     mock_cand_repo, mock_video_repo, mock_clip_repo,
     mock_transcript_repo, mock_segment_repo, completed) = _make_service_with_mocks()

    mock_settings = MagicMock()
    mock_settings.USE_AUTO_HOOK = True
    mock_settings.AUTO_HOOK_MIN_CONFIDENCE = 0.6
    mock_settings.AUTO_HOOK_MIN_WINDOW_SECONDS = 20.0

    mock_transcript = MagicMock()
    mock_transcript.id = 10
    mock_transcript_repo.get_by_video.return_value = mock_transcript
    mock_segment_repo.get_by_transcript.return_value = []

    with patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("app.services.clip_service.subprocess.run", return_value=completed), \
         patch("app.services.clip_service.settings", mock_settings), \
         patch(
             "app.ai_modules.hook_analysis.hook_moment_finder.HookMomentFinder.find",
             side_effect=RuntimeError("LLM timeout sengaja"),
         ):

        service = _build_service(
            mock_db, mock_cand_repo, mock_video_repo, mock_clip_repo,
            mock_transcript_repo, mock_segment_repo,
        )
        # TIDAK boleh raise
        clip = service.generate_clip(1, "9:16")

    assert clip is not None
    assert clip.id == 99


def test_hook_composer_skip_window_too_short() -> None:
    """HookComposerService.compose() dengan window < min → hook_skip_reason=window_too_short, return False."""
    from app.services.hook_composer_service import HookComposerService
    from app.ai_modules.hook_analysis.hook_moment_finder import HookMoment

    mock_db = MagicMock()
    mock_clip = MagicMock()
    mock_clip.id = 1

    mock_clip_repo = MagicMock()
    mock_clip_repo.get.return_value = mock_clip

    mock_settings = MagicMock()
    mock_settings.USE_AUTO_HOOK = True
    mock_settings.AUTO_HOOK_MIN_WINDOW_SECONDS = 20.0

    dummy_hook = HookMoment(
        hook_moment_start=5.0, hook_moment_end=7.0,
        hook_type="shock", hook_confidence=0.9,
        hook_caption="Test caption", best_idx=2,
    )

    with patch("app.services.hook_composer_service.settings", mock_settings):
        service = HookComposerService(mock_db)
        service.clip_repo = mock_clip_repo

        result = service.compose(
            clip_id=1,
            video_source_path="C:/dummy.mp4",
            aspect_ratio="9:16",
            hook_moment=dummy_hook,
            window_duration=10.0,  # < 20.0 → too short
        )

    assert result is False
    assert mock_clip.hook_skip_reason == "window_too_short"
    mock_db.commit.assert_called()


def test_hook_composer_disabled_flag() -> None:
    """USE_AUTO_HOOK=False → compose() langsung return False tanpa render."""
    from app.services.hook_composer_service import HookComposerService
    from app.ai_modules.hook_analysis.hook_moment_finder import HookMoment

    mock_db = MagicMock()
    mock_clip = MagicMock()
    mock_clip_repo = MagicMock()
    mock_clip_repo.get.return_value = mock_clip

    mock_settings = MagicMock()
    mock_settings.USE_AUTO_HOOK = False

    dummy_hook = HookMoment(
        hook_moment_start=30.0, hook_moment_end=32.0,
        hook_type="shock", hook_confidence=0.9,
        hook_caption="Test", best_idx=6,
    )

    with patch("app.services.hook_composer_service.settings", mock_settings):
        service = HookComposerService(mock_db)
        service.clip_repo = mock_clip_repo
        result = service.compose(
            clip_id=1,
            video_source_path="C:/dummy.mp4",
            aspect_ratio="9:16",
            hook_moment=dummy_hook,
            window_duration=60.0,
        )

    assert result is False
    assert mock_clip.hook_skip_reason == "disabled"


# ── Watermark drag (add_watermark x_pct/y_pct) tests ──────────────────────────

def _make_watermark_service(tmp_path):
    """ClipEditorService dengan deps di-mock + WATERMARK_PATH di tmp_path."""
    from app.services.clip_editor_service import ClipEditorService

    clip = MagicMock()
    clip.id = 3
    clip.file_path = "C:/output/clip_9.mp4"
    clip.edited_file_path = None
    clip.start_time = 0.0
    clip.end_time = 10.0
    clip.has_watermark = False

    repo = MagicMock()
    repo.get.return_value = clip

    ffmpeg = MagicMock()
    ffmpeg.extract_metadata.return_value = {"width": 1920, "height": 1080}

    service = ClipEditorService(MagicMock())
    service.clip_repo = repo
    service.ffmpeg = ffmpeg

    mock_settings = MagicMock()
    mock_settings.WATERMARK_PATH = tmp_path / "assets" / "watermark.png"
    return service, clip, mock_settings


def _run_watermark(service, mock_settings, **kw):
    """Patch settings + subprocess + Path ops, jalankan add_watermark."""
    import subprocess as sp
    mock_settings.WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    mock_settings.WATERMARK_PATH.write_bytes(b"png")  # supaya exists() True
    completed = MagicMock()
    completed.returncode = 0
    with patch("app.services.clip_editor_service.settings", mock_settings), \
         patch("app.services.clip_editor_service.subprocess.run", return_value=completed) as m, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.rename"):
        service.add_watermark(3, **kw)
    return m


def test_add_watermark_drag_uses_xpct_ypct(tmp_path) -> None:
    """add_watermark dengan x_pct/y_pct → ekspresi overlay pakai pct, bukan position_map."""
    service, _, mock_settings = _make_watermark_service(tmp_path)

    m = _run_watermark(service, mock_settings, x_pct=0.25, y_pct=0.75, scale=0.30, opacity=0.8)

    fc = m.call_args[0][0][m.call_args[0][0].index("-filter_complex") + 1]
    assert "(main_w-overlay_w)*0.25" in fc
    assert "(main_h-overlay_h)*0.75" in fc
    assert "main_w-overlay_w-10" not in fc  # bukan jalur margin


def test_add_watermark_validation_xpct_ypct(tmp_path) -> None:
    """x_pct=1.5 / y_pct=-0.1 → ValidationException."""
    from app.core.exceptions.base import ValidationException

    service, _, mock_settings = _make_watermark_service(tmp_path)

    with pytest.raises(ValidationException, match="x_pct"):
        _run_watermark(service, mock_settings, x_pct=1.5, y_pct=0.5)
    with pytest.raises(ValidationException, match="y_pct"):
        _run_watermark(service, mock_settings, x_pct=0.5, y_pct=-0.1)


def test_add_watermark_backward_compat_no_pct(tmp_path) -> None:
    """Tanpa x_pct/y_pct → pakai position_map (behavior lama)."""
    service, _, mock_settings = _make_watermark_service(tmp_path)

    m = _run_watermark(service, mock_settings, position="top_right", scale=0.30, opacity=0.8)

    fc = m.call_args[0][0][m.call_args[0][0].index("-filter_complex") + 1]
    assert "main_w-overlay_w-10" in fc  # position_map top_right pakai margin

    # JSON position file TIDAK ditulis
    assert not (tmp_path / "assets" / "watermark_position.json").exists()


def test_add_watermark_writes_position_file_on_drag(tmp_path) -> None:
    """Dengan x_pct/y_pct → watermark_position.json ditulis sesuai isi."""
    import json

    service, _, mock_settings = _make_watermark_service(tmp_path)

    _run_watermark(service, mock_settings, x_pct=0.2, y_pct=0.8, scale=0.25, opacity=0.7)

    data = json.loads((tmp_path / "assets" / "watermark_position.json").read_text(encoding="utf-8"))
    assert data["x_pct"] == 0.2
    assert data["y_pct"] == 0.8
    assert data["scale"] == 0.25
    assert data["opacity"] == 0.7


def test_get_last_watermark_position_default_and_file(tmp_path) -> None:
    """get_last_watermark_position: default saat file belum ada, isi saat ada."""
    import json

    service, _, mock_settings = _make_watermark_service(tmp_path)
    pos_file = tmp_path / "assets" / "watermark_position.json"

    with patch("app.services.clip_editor_service.settings", mock_settings):
        d = service.get_last_watermark_position()
        assert d == {"x_pct": 0.65, "y_pct": 0.80, "scale": 0.30, "opacity": 0.8}

        pos_file.parent.mkdir(parents=True, exist_ok=True)
        pos_file.write_text(json.dumps({"x_pct": 0.1, "y_pct": 0.9, "scale": 0.5, "opacity": 0.4}), encoding="utf-8")
        d = service.get_last_watermark_position()
        assert d["x_pct"] == 0.1 and d["y_pct"] == 0.9
        assert d["scale"] == 0.5 and d["opacity"] == 0.4

        # file corrupt → default
        pos_file.write_text("bukan json", encoding="utf-8")
        d = service.get_last_watermark_position()
        assert d == {"x_pct": 0.65, "y_pct": 0.80, "scale": 0.30, "opacity": 0.8}
