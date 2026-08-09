"""Tests for FaceEmotionAnalyzer using mock cv2/mediapipe Tasks."""

from unittest.mock import MagicMock, patch

import numpy as np

from app.ai_modules.base.analyzer_interface import AnalyzerUnavailable
from app.ai_modules.face_analysis.face_emotion_analyzer import FaceEmotionAnalyzer


class _MockLandmark:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


def _frame():
    """Dummy numpy frame (480x640x3)."""
    return np.zeros((480, 640, 3), dtype=np.uint8)


def _face_landmarks():
    """Landmark (0.5,0.5) semua; mulut sedikit terbuka."""
    points = {}
    for i in range(478):
        points[i] = _MockLandmark(0.5, 0.5)
    # Mouth terbuka: jarak vertikal > horizontal
    points[39] = _MockLandmark(0.48, 0.42)   # atas mulut
    points[181] = _MockLandmark(0.52, 0.58)  # bawah mulut
    return [points[i] for i in range(478)]  # list NormalizedLandmark-like


def _mock_landmarker(result_face_landmarks):
    """Bikin mock FaceLandmarker + create_from_options yang return instance."""
    landmarker = MagicMock()
    result = MagicMock()
    result.face_landmarks = result_face_landmarks
    landmarker.detect.return_value = result
    mock_class = MagicMock()
    mock_class.create_from_options.return_value = landmarker
    with patch("app.ai_modules.face_analysis.face_emotion_analyzer.FaceLandmarker", mock_class), \
         patch("app.ai_modules.face_analysis.face_emotion_analyzer.ensure_model", return_value="dummy.task"):
        yield landmarker


def test_face_emotion_analyze_success() -> None:
    """Analyze dengan wajah terdeteksi → skor dalam 0-10, reason ada."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 30.0
    mock_cap.read.return_value = (True, _frame())

    gen = _mock_landmarker([_face_landmarks()])
    landmarker = next(gen)

    analyzer = FaceEmotionAnalyzer()
    with patch("cv2.VideoCapture", return_value=mock_cap):
        result = analyzer.analyze({"video_path": "dummy.mp4", "start": 0, "end": 10})

    assert 0.0 <= result.score <= 10.0
    assert "reason" in result.result_data
    assert result.result_data["frames_analyzed"] > 0
    landmarker.detect.assert_called()
    gen.close()


def test_face_emotion_no_face_neutral() -> None:
    """Tanpa wajah terdeteksi → skor netral 5.0."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 30.0
    mock_cap.read.return_value = (True, _frame())

    gen = _mock_landmarker([])  # face_landmarks kosong
    next(gen)

    analyzer = FaceEmotionAnalyzer()
    with patch("cv2.VideoCapture", return_value=mock_cap):
        result = analyzer.analyze({"video_path": "dummy.mp4", "start": 0, "end": 10})

    assert result.score == 5.0
    assert "Tidak ada wajah" in result.result_data["reason"]
    gen.close()


def test_face_emotion_unavailable_on_missing_video() -> None:
    """Video tidak bisa dibuka → AnalyzerUnavailable."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False

    gen = _mock_landmarker([])
    next(gen)

    analyzer = FaceEmotionAnalyzer()
    with patch("cv2.VideoCapture", return_value=mock_cap):
        try:
            analyzer.analyze({"video_path": "missing.mp4", "start": 0, "end": 5})
            assert False, "should raise"
        except AnalyzerUnavailable:
            pass
    gen.close()
