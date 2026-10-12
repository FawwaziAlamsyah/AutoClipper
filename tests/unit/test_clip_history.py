"""Unit tests for ClipHistoryManager, Undo/Redo rollback, and Hook chaining."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions.base import ValidationException
from app.services.clip_history_manager import ClipHistoryManager
from app.services.clip_editor_service import ClipEditorService


@pytest.fixture
def mock_clip():
    clip = MagicMock()
    clip.id = 42
    clip.file_path = "data/outputs/clip_42_original.mp4"
    clip.edited_file_path = None
    clip.start_time = 10.0
    clip.end_time = 40.0
    clip.hook_applied = False
    return clip


@pytest.fixture
def history_mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.settings.OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr("app.core.config.settings.settings.TEMP_DIR", tmp_path / "temp")
    mgr = ClipHistoryManager(clip_id=42)
    return mgr


def test_init_history_original(history_mgr, mock_clip):
    """Clip baru tanpa edited_file_path diinisialisasi dengan Step 0 Klip Original."""
    status = history_mgr.get_status(mock_clip)
    assert status["can_undo"] is False
    assert status["can_redo"] is False
    assert status["current_step"] == 0
    assert status["total_steps"] == 1
    assert status["current_label"] == "Klip Original"


def test_push_step_and_undo(history_mgr, mock_clip, tmp_path):
    """Push step baru memungkinkan undo 1 langkah mundur."""
    # Buat dummy temp file
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    step1_temp = temp_dir / "temp_trim.mp4"
    step1_temp.write_bytes(b"trim-content")

    # Push step 1 (Trim)
    status = history_mgr.push_step(
        clip=mock_clip,
        action="trim",
        label="Trim 12.0s - 35.0s",
        temp_file_path=step1_temp,
        new_start_time=12.0,
        new_end_time=35.0,
    )

    assert status["can_undo"] is True
    assert status["can_redo"] is False
    assert status["current_step"] == 1
    assert status["total_steps"] == 2
    assert status["current_label"] == "Trim 12.0s - 35.0s"
    assert mock_clip.start_time == 12.0
    assert mock_clip.end_time == 35.0
    assert "step_1_trim" in mock_clip.edited_file_path

    # Push step 2 (Watermark)
    step2_temp = temp_dir / "temp_wm.mp4"
    step2_temp.write_bytes(b"watermark-content")
    status2 = history_mgr.push_step(
        clip=mock_clip,
        action="watermark",
        label="Watermark",
        temp_file_path=step2_temp,
    )
    assert status2["current_step"] == 2
    assert status2["total_steps"] == 3

    # Undo 1-step (kembali ke Trim)
    undo_status = history_mgr.undo(mock_clip)
    assert undo_status["current_step"] == 1
    assert undo_status["can_undo"] is True
    assert undo_status["can_redo"] is True
    assert undo_status["current_label"] == "Trim 12.0s - 35.0s"
    assert "step_1_trim" in mock_clip.edited_file_path

    # Undo 1-step lagi (kembali ke Klip Original)
    undo_status_orig = history_mgr.undo(mock_clip)
    assert undo_status_orig["current_step"] == 0
    assert undo_status_orig["can_undo"] is False
    assert undo_status_orig["can_redo"] is True
    assert mock_clip.edited_file_path is None
    assert mock_clip.start_time == 10.0
    assert mock_clip.end_time == 40.0


def test_redo_flow(history_mgr, mock_clip, tmp_path):
    """Redo melangkah maju setelah langkah di-undo."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / "temp.mp4"
    temp_file.write_bytes(b"content")

    history_mgr.push_step(mock_clip, "text", "Teks: Promo", temp_file)
    assert history_mgr.get_status(mock_clip)["current_step"] == 1

    # Undo
    history_mgr.undo(mock_clip)
    assert history_mgr.get_status(mock_clip)["current_step"] == 0

    # Redo
    redo_status = history_mgr.redo(mock_clip)
    assert redo_status["current_step"] == 1
    assert redo_status["can_redo"] is False
    assert "step_1_text" in mock_clip.edited_file_path


def test_truncate_redo_on_new_edit(history_mgr, mock_clip, tmp_path):
    """Edit baru saat di tengah stack memotong langkah redo yang sudah dibatalkan."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    f1 = temp_dir / "f1.mp4"
    f1.write_bytes(b"1")
    history_mgr.push_step(mock_clip, "trim", "Trim", f1)

    f2 = temp_dir / "f2.mp4"
    f2.write_bytes(b"2")
    history_mgr.push_step(mock_clip, "watermark", "WM", f2)
    assert history_mgr.get_status(mock_clip)["total_steps"] == 3

    # Undo to step 1
    history_mgr.undo(mock_clip)
    assert history_mgr.get_status(mock_clip)["current_step"] == 1

    # New edit from step 1
    f3 = temp_dir / "f3.mp4"
    f3.write_bytes(b"3")
    history_mgr.push_step(mock_clip, "sound", "Sound", f3)

    new_status = history_mgr.get_status(mock_clip)
    assert new_status["current_step"] == 2
    assert new_status["total_steps"] == 3
    assert new_status["current_label"] == "Sound"
    assert new_status["can_redo"] is False


def test_hook_chaining_picks_latest_non_hook_step(history_mgr, mock_clip, tmp_path):
    """Hook mengambil video hasil edit/trim aktif, bukan video mentah awal.
    Dan jika hook di-generate ulang, ia mengambil basis sebelum hook (anti double-teaser)."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 1. User melakukan trim
    f1 = temp_dir / "trim.mp4"
    f1.write_bytes(b"trimmed-clip")
    history_mgr.push_step(mock_clip, "trim", "Trim 5s-20s", f1, new_start_time=15.0, new_end_time=30.0)

    # get_base_for_hook harus mengembalikan video yang sudah di-trim!
    base_for_hook = history_mgr.get_base_for_hook(mock_clip)
    assert "step_1_trim" in str(base_for_hook)

    # 2. User memasang Hook
    f_hook = temp_dir / "hook.mp4"
    f_hook.write_bytes(b"hooked-clip")
    history_mgr.push_step(mock_clip, "hook", "AI Hook Teaser", f_hook, hook_applied=True)

    # 3. User mengubah caption dan klik Generate Ulang Hook
    # Base untuk hook berikutnya harus tetap video Trim (step 1), bukan video ber-hook ganda!
    base_for_rehook = history_mgr.get_base_for_hook(mock_clip)
    assert "step_1_trim" in str(base_for_rehook)


def test_reset_clears_all_history(history_mgr, mock_clip, tmp_path):
    """Reset menghapus file riwayat dan mengembalikan clip ke original."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    f1 = temp_dir / "trim.mp4"
    f1.write_bytes(b"trim")

    history_mgr.push_step(mock_clip, "trim", "Trim", f1, new_start_time=15.0, new_end_time=25.0)
    assert history_mgr.get_status(mock_clip)["current_step"] == 1

    history_mgr.reset(mock_clip, original_start_time=10.0, original_end_time=40.0)
    assert mock_clip.edited_file_path is None
    assert mock_clip.start_time == 10.0
    assert mock_clip.end_time == 40.0
    status = history_mgr.get_status(mock_clip)
    assert status["current_step"] == 0
    assert status["can_undo"] is False


def test_clip_editor_service_undo_redo():
    """ClipEditorService exposes undo dan redo methods."""
    mock_db = MagicMock()
    service = ClipEditorService(mock_db)

    clip = MagicMock()
    clip.id = 99
    service.clip_repo = MagicMock()
    service.clip_repo.get.return_value = clip

    with patch.object(ClipHistoryManager, "undo") as mock_undo, \
         patch.object(ClipHistoryManager, "redo") as mock_redo:
        service.undo(99)
        mock_undo.assert_called_once_with(clip)
        mock_db.commit.assert_called()

        service.redo(99)
        mock_redo.assert_called_once_with(clip)
