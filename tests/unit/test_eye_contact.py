"""Tests for EyeContactAnalyzer using mock cv2/mediapipe Tasks."""

from unittest.mock import MagicMock, patch

import numpy as np

from app.ai_modules.face_analysis.eye_contact_analyzer import EyeContactAnalyzer


class _MockLandmark:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


def _frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)


def _face_landmarks():
    """Landmark seragam; mata terbuka (EAR tinggi), nose di tengah."""
    points = {}
    for i in range(478):
        points[i] = _MockLandmark(0.5, 0.5)
    points[33] = _MockLandmark(0.45, 0.45)   # kiri mata kiri
    points[133] = _MockLandmark(0.47, 0.45)  # kanan mata kiri
    points[160] = _MockLandmark(0.46, 0.41)  # atas
    points[144] = _MockLandmark(0.46, 0.49)  # bawah
    points[158] = _MockLandmark(0.46, 0.42)
    points[153] = _MockLandmark(0.46, 0.48)
    points[362] = _MockLandmark(0.53, 0.45)  # mata kanan
    points[263] = _MockLandmark(0.55, 0.45)
    points[385] = _MockLandmark(0.54, 0.41)
    points[373] = _MockLandmark(0.54, 0.49)
    points[387] = _MockLandmark(0.54, 0.42)
    points[380] = _MockLandmark(0.54, 0.48)
    points[1] = _MockLandmark(0.5, 0.5)  # nose tengah (menghadap kamera)
    return [points[i] for i in range(478)]


def test_eye_contact_analyze() -> None:
    """Mata terbuka + head frontal → skor tinggi."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 30.0
    mock_cap.read.return_value = (True, _frame())

    landmarker = MagicMock()
    result = MagicMock()
    result.face_landmarks = [_face_landmarks()]
    landmarker.detect.return_value = result
    mock_class = MagicMock()
    mock_class.create_from_options.return_value = landmarker

    analyzer = EyeContactAnalyzer()
    with patch("app.ai_modules.face_analysis.eye_contact_analyzer.FaceLandmarker", mock_class), \
         patch("app.ai_modules.face_analysis.eye_contact_analyzer.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=mock_cap):
        result2 = analyzer.analyze({"video_path": "dummy.mp4", "start": 0, "end": 10})

    assert 0.0 <= result2.score <= 10.0
    assert result2.result_data["front_facing_ratio"] > 0.5
    assert "reason" in result2.result_data
