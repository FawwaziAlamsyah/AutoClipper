"""Tests for SceneChangeAnalyzer using mock cv2."""

from unittest.mock import MagicMock, patch

import numpy as np

from app.ai_modules.scene_analysis.scene_change_analyzer import SceneChangeAnalyzer


def _frame(brightness: float = 0.0):
    return np.full((480, 640, 3), brightness, dtype=np.uint8)


@patch("cv2.VideoCapture")
def test_scene_change_analyze(MockCap: MagicMock) -> None:
    """Frame berganti terang/gelap → deteksi scene change, skor 0-10."""
    frames = [_frame(255), _frame(0), _frame(255), _frame(0)]
    MockCap.return_value.isOpened.return_value = True
    MockCap.return_value.get.return_value = 30.0
    MockCap.return_value.read.side_effect = [(True, f) for f in frames] + [(False, None)]

    analyzer = SceneChangeAnalyzer()
    result = analyzer.analyze({"video_path": "dummy.mp4", "start": 0, "end": 1})

    assert 0.0 <= result.score <= 10.0
    assert result.result_data["scene_changes"] >= 1
    assert "reason" in result.result_data


@patch("cv2.VideoCapture")
def test_scene_change_static(MockCap: MagicMock) -> None:
    """Frame statis (tanpa perubahan) → skor rendah (kurang dinamis)."""
    frames = [_frame(128)] * 5
    MockCap.return_value.isOpened.return_value = True
    MockCap.return_value.get.return_value = 30.0
    MockCap.return_value.read.side_effect = [(True, f) for f in frames] + [(False, None)]

    analyzer = SceneChangeAnalyzer()
    result = analyzer.analyze({"video_path": "dummy.mp4", "start": 0, "end": 1})

    assert 0.0 <= result.score <= 10.0
    assert result.result_data["scene_changes"] == 0
