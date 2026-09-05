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
