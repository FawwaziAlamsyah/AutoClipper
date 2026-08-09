"""Tests for GestureAnalyzer using mock cv2/mediapipe Tasks."""

from unittest.mock import MagicMock, patch

import numpy as np

from app.ai_modules.gesture_analysis.gesture_analyzer import GestureAnalyzer


class _MockLandmark:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


def _frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)


def _hand_landmarks():
    return [_MockLandmark(0.4 + i * 0.01, 0.5) for i in range(21)]


def test_gesture_analyze_success() -> None:
    """Gesture dengan tangan terdeteksi → skor 0-10."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 30.0
    mock_cap.read.return_value = (True, _frame())

    hands = MagicMock()
    result = MagicMock()
    result.hand_landmarks = [_hand_landmarks()]
    hands.detect.return_value = result
    mock_class = MagicMock()
    mock_class.create_from_options.return_value = hands

    analyzer = GestureAnalyzer()
    with patch("app.ai_modules.gesture_analysis.gesture_analyzer.HandLandmarker", mock_class), \
         patch("app.ai_modules.gesture_analysis.gesture_analyzer.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=mock_cap):
        result2 = analyzer.analyze({"video_path": "dummy.mp4", "start": 0, "end": 10})

    assert 0.0 <= result2.score <= 10.0
    assert "reason" in result2.result_data
    assert result2.result_data["frames_with_hands"] > 0


def test_gesture_no_hands_neutral() -> None:
    """Tanpa tangan → skor netral 5.0."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 30.0
    mock_cap.read.return_value = (True, _frame())

    hands = MagicMock()
    result = MagicMock()
    result.hand_landmarks = []
    hands.detect.return_value = result
    mock_class = MagicMock()
    mock_class.create_from_options.return_value = hands

    analyzer = GestureAnalyzer()
    with patch("app.ai_modules.gesture_analysis.gesture_analyzer.HandLandmarker", mock_class), \
         patch("app.ai_modules.gesture_analysis.gesture_analyzer.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=mock_cap):
        result2 = analyzer.analyze({"video_path": "dummy.mp4", "start": 0, "end": 10})

    assert result2.score == 5.0
    assert "Tidak ada tangan" in result2.result_data["reason"]
