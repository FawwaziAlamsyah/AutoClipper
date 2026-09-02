"""Tests for VideoVisionPass — single-pass visual analyzer.

Verifikasi:
1. analyze_window() menghasilkan ke-4 key (face_emotion, eye_contact, gesture, scene)
2. Skor face_emotion dengan wajah terdeteksi > 5.0 (lebih baik dari netral)
3. Skor gesture dengan tangan terdeteksi > 5.0
4. Skor eye_contact dengan kepala frontal > 5.0
5. Skor scene dengan perubahan frame > nilai statis
6. Skor netral 5.0 saat tidak ada wajah / tangan
7. AnalyzerUnavailable saat video tidak bisa dibuka
8. VideoCapture hanya dibuka SEKALI per window (bottleneck utama yang difixnya)
"""

from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from app.ai_modules.base.analyzer_interface import AnalyzerUnavailable
from app.ai_modules.video_vision_pass import VideoVisionPass


# ── Helpers ──────────────────────────────────────────────────────────────────

class _MockLandmark:
    def __init__(self, x: float = 0.5, y: float = 0.5) -> None:
        self.x = x
        self.y = y


def _frame(brightness: int = 0) -> np.ndarray:
    return np.full((480, 640, 3), brightness, dtype=np.uint8)


def _face_landmarks_open_eyes():
    """Landmark wajah dengan mata terbuka (EAR tinggi) dan hidung di tengah."""
    lm = {i: _MockLandmark(0.5, 0.5) for i in range(478)}
    # LEFT_EYE [33, 160, 158, 133, 153, 144] — EAR tinggi
    lm[33]  = _MockLandmark(0.45, 0.45)
    lm[133] = _MockLandmark(0.47, 0.45)
    lm[160] = _MockLandmark(0.46, 0.41)
    lm[144] = _MockLandmark(0.46, 0.49)
    lm[158] = _MockLandmark(0.46, 0.42)
    lm[153] = _MockLandmark(0.46, 0.48)
    # RIGHT_EYE [362, 385, 387, 263, 373, 380]
    lm[362] = _MockLandmark(0.53, 0.45)
    lm[263] = _MockLandmark(0.55, 0.45)
    lm[385] = _MockLandmark(0.54, 0.41)
    lm[373] = _MockLandmark(0.54, 0.49)
    lm[387] = _MockLandmark(0.54, 0.42)
    lm[380] = _MockLandmark(0.54, 0.48)
    # MOUTH [61, 39, 0, 269, 291, 181] — mulut sedikit terbuka
    lm[61]  = _MockLandmark(0.48, 0.70)
    lm[291] = _MockLandmark(0.52, 0.70)
    lm[39]  = _MockLandmark(0.49, 0.67)
    lm[181] = _MockLandmark(0.49, 0.73)
    lm[0]   = _MockLandmark(0.50, 0.65)
    lm[269] = _MockLandmark(0.51, 0.73)
    # NOSE_TIP [1] — di tengah (menghadap kamera)
    lm[1]   = _MockLandmark(0.50, 0.50)
    return [lm[i] for i in range(478)]


def _hand_landmarks():
    """21 landmark tangan dengan posisi berbeda antar dua 'frame' untuk simulasi motion."""
    return [_MockLandmark(0.4 + i * 0.01, 0.5) for i in range(21)]


def _make_face_mock(has_face: bool):
    """Return (mock FaceLandmarker class, instance) dengan hasil sesuai has_face."""
    landmarker = MagicMock()
    face_result = MagicMock()
    face_result.face_landmarks = [_face_landmarks_open_eyes()] if has_face else []
    landmarker.detect.return_value = face_result
    mock_class = MagicMock()
    mock_class.create_from_options.return_value = landmarker
    return mock_class, landmarker


def _make_hand_mock(has_hand: bool):
    """Return (mock HandLandmarker class, instance)."""
    hand_lm = MagicMock()
    hand_result = MagicMock()
    hand_result.hand_landmarks = [_hand_landmarks()] if has_hand else []
    hand_lm.detect.return_value = hand_result
    mock_class = MagicMock()
    mock_class.create_from_options.return_value = hand_lm
    return mock_class, hand_lm


def _make_cap(frames: list[np.ndarray]):
    """Return mock VideoCapture yang iterasi frames lalu (False, None)."""
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.return_value = 30.0
    cap.read.side_effect = [(True, f) for f in frames] + [(False, None)]
    return cap


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_analyze_window_returns_all_four_keys():
    """analyze_window() harus return dict dengan 4 key analyzer."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    cap = _make_cap([_frame(128)] * 5)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    assert set(results.keys()) == {"face_emotion", "eye_contact", "gesture", "scene"}
    for result in results.values():
        assert 0.0 <= result.score <= 10.0


def test_face_with_open_eyes_scores_above_neutral():
    """Wajah terdeteksi + mata terbuka → face_emotion dan eye_contact > 5.0."""
    face_cls, _ = _make_face_mock(has_face=True)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    cap = _make_cap([_frame(128)] * 10)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    assert results["face_emotion"].score > 5.0, \
        f"Expected face_emotion > 5.0, got {results['face_emotion'].score}"
    assert results["eye_contact"].score > 5.0, \
        f"Expected eye_contact > 5.0, got {results['eye_contact'].score}"
    assert "reason" in results["face_emotion"].result_data
    assert "reason" in results["eye_contact"].result_data
    assert results["eye_contact"].result_data["front_facing_ratio"] > 0.5


def test_hand_detected_gesture_above_neutral():
    """Tangan terdeteksi → gesture > 5.0."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=True)
    cap = _make_cap([_frame(128)] * 10)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    assert results["gesture"].score > 5.0, \
        f"Expected gesture > 5.0, got {results['gesture'].score}"
    assert results["gesture"].result_data["frames_with_hands"] > 0


def test_no_face_no_hand_neutral_scores():
    """Tanpa wajah dan tangan → face_emotion, eye_contact, gesture = 5.0."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    cap = _make_cap([_frame(128)] * 5)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    assert results["face_emotion"].score == 5.0
    assert results["eye_contact"].score == 5.0
    assert results["gesture"].score == 5.0


def test_scene_change_detected():
    """Frame berganti brightness tinggi/rendah → scene_changes ≥ 1."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    # Alternating bright/dark frames → banyak scene change
    frames = [_frame(255), _frame(0), _frame(255), _frame(0), _frame(255)]
    cap = _make_cap(frames)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 5.0)

    assert results["scene"].result_data["scene_changes"] >= 1
    assert 0.0 <= results["scene"].score <= 10.0


def test_scene_static_score_valid():
    """Frame statis (tidak berubah) → scene_changes = 0, skor tetap valid 0-10."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    frames = [_frame(128)] * 6
    cap = _make_cap(frames)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 5.0)

    assert results["scene"].result_data["scene_changes"] == 0
    assert 0.0 <= results["scene"].score <= 10.0


def test_unavailable_on_cannot_open_video():
    """Video tidak bisa dibuka → AnalyzerUnavailable."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    cap = MagicMock()
    cap.isOpened.return_value = False

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        with pytest.raises(AnalyzerUnavailable):
            vvp.analyze_window("missing.mp4", 0.0, 10.0)


def test_unavailable_on_empty_path():
    """video_path kosong → AnalyzerUnavailable tanpa membuka VideoCapture."""
    vvp = VideoVisionPass()
    with pytest.raises(AnalyzerUnavailable):
        vvp.analyze_window("", 0.0, 10.0)


def test_single_videocapture_per_window():
    """VideoCapture hanya dibuka SEKALI per analyze_window() — ini bottleneck utama."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    cap = _make_cap([_frame(128)] * 5)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap) as mock_cv2_cap:
        vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    # VideoCapture hanya dibuka 1x (bukan 4x seperti jalur lama)
    assert mock_cv2_cap.call_count == 1, \
        f"VideoCapture seharusnya dipanggil 1x, tapi dipanggil {mock_cv2_cap.call_count}x"


def test_face_landmarker_detect_called_once_per_frame():
    """FaceLandmarker.detect() dipanggil SEKALI per frame (bukan sekali per analyzer)."""
    face_cls, face_instance = _make_face_mock(has_face=True)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    n_frames = 5
    cap = _make_cap([_frame(128)] * n_frames)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    # detect() dipanggil sekali per frame (bukan 2x untuk face_emotion+eye_contact)
    assert face_instance.detect.call_count == n_frames, \
        f"FaceLandmarker.detect seharusnya {n_frames}x, tapi {face_instance.detect.call_count}x"


def test_model_reused_across_windows():
    """FaceLandmarker dan HandLandmarker di-build sekali, di-reuse lintas window."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    cap = _make_cap([_frame(128)] * 3)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        # Panggil analyze_window dua kali (simulasi dua window)
        vvp.analyze_window("dummy.mp4", 0.0, 5.0)
        cap.read.side_effect = [(True, _frame(128))] * 3 + [(False, None)]
        cap.isOpened.return_value = True
        vvp.analyze_window("dummy.mp4", 5.0, 10.0)

    # create_from_options hanya dipanggil sekali untuk masing-masing model
    assert face_cls.create_from_options.call_count == 1, \
        "FaceLandmarker.create_from_options seharusnya hanya 1x per VideoVisionPass instance"
    assert hand_cls.create_from_options.call_count == 1, \
        "HandLandmarker.create_from_options seharusnya hanya 1x per VideoVisionPass instance"


def test_result_data_has_required_fields_face_emotion():
    """result_data face_emotion memiliki semua field yang diharapkan downstream."""
    face_cls, _ = _make_face_mock(has_face=True)
    hand_cls, _ = _make_hand_mock(has_hand=False)
    cap = _make_cap([_frame(128)] * 5)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    fe = results["face_emotion"].result_data
    for key in ("reason", "avg_mouth_aspect_ratio", "avg_eye_aspect_ratio",
                "frames_analyzed", "frames_with_face"):
        assert key in fe, f"Key '{key}' tidak ada di face_emotion.result_data"

    ec = results["eye_contact"].result_data
    for key in ("reason", "avg_eye_aspect_ratio", "front_facing_ratio",
                "frames_analyzed", "frames_with_face"):
        assert key in ec, f"Key '{key}' tidak ada di eye_contact.result_data"


def test_result_data_has_required_fields_gesture():
    """result_data gesture memiliki semua field yang diharapkan downstream."""
    face_cls, _ = _make_face_mock(has_face=False)
    hand_cls, _ = _make_hand_mock(has_hand=True)
    cap = _make_cap([_frame(128)] * 5)

    vvp = VideoVisionPass()
    with patch("app.ai_modules.video_vision_pass.FaceLandmarker", face_cls), \
         patch("app.ai_modules.video_vision_pass.HandLandmarker", hand_cls), \
         patch("app.ai_modules.video_vision_pass.ensure_model", return_value="dummy.task"), \
         patch("cv2.VideoCapture", return_value=cap):
        results = vvp.analyze_window("dummy.mp4", 0.0, 10.0)

    g = results["gesture"].result_data
    for key in ("reason", "frames_analyzed", "frames_with_hands",
                "avg_hand_motion", "hand_presence_ratio"):
        assert key in g, f"Key '{key}' tidak ada di gesture.result_data"
