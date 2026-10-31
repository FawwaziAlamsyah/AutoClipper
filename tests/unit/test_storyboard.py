"""Unit tests for StoryboardService."""

from pathlib import Path
import numpy as np
import cv2
import pytest

from app.services.storyboard_service import StoryboardService


@pytest.fixture
def temp_dummy_video(tmp_path: Path) -> str:
    """Buat file video mp4 sintetis berdurasi 3 detik (75 frames @ 25fps)."""
    video_path = str(tmp_path / "dummy_test.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, 25.0, (320, 180))

    # Frame 0-35: merah, Frame 36-74: hijau (memicu scene cut)
    for i in range(75):
        color = (0, 0, 255) if i < 36 else (0, 255, 0)
        frame = np.full((180, 320, 3), color, dtype=np.uint8)
        out.write(frame)
    out.release()
    return video_path


def test_storyboard_generation(temp_dummy_video: str):
    """Test pembuatan storyboard grid sheets dan scene cut detection."""
    service = StoryboardService(
        frame_width=160,
        frame_height=90,
        grid_cols=4,
        grid_rows=4,
        max_total_frames=50,
        target_interval=0.5,
    )

    sheets, scene_cuts = service.generate_storyboard(temp_dummy_video)

    assert len(sheets) >= 1
    # Sheet harus berupa data URI base64 JPEG
    assert sheets[0].startswith("data:image/jpeg;base64,")
    # Scene cut terdeteksi di sekitar pergantian warna frame 36 (~1.4s)
    assert len(scene_cuts) >= 1
    assert any(1.0 <= sc <= 2.0 for sc in scene_cuts)


def test_storyboard_empty_video(tmp_path: Path):
    """Test penanganan file video yang tidak ada."""
    service = StoryboardService()
    sheets, scene_cuts = service.generate_storyboard(str(tmp_path / "non_existent.mp4"))
    assert sheets == []
    assert scene_cuts == []


def test_format_timestamp():
    """Test format timestamp MM:SS dan HH:MM:SS."""
    assert StoryboardService._format_timestamp(45) == "00:45"
    assert StoryboardService._format_timestamp(125) == "02:05"
    assert StoryboardService._format_timestamp(3665) == "01:01:05"
