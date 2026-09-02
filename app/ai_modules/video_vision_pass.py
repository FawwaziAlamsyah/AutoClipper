"""VideoVisionPass — single-pass decode untuk 4 analyzer visual sekaligus.

Menggantikan pola lama di mana face_emotion, eye_contact, gesture, dan scene
masing-masing membuka cv2.VideoCapture, seek, dan decode frame secara terpisah
(4 × N_window kali buka/seek/decode). Dengan single-pass, video hanya dibuka
SEKALI per window, frame di-decode SEKALI, dan hasil deteksi FaceLandmarker
serta HandLandmarker di-share ke semua analyzer yang membutuhkannya.

Perbandingan beban:
  Lama : 4 VideoCapture + 4 seek + decode 300×4 frame per window
  Baru : 1 VideoCapture + 1 seek + decode ≤300 frame per window
  Estimasi speedup: ~3-4× untuk kelompok visual (tidak memperhitungkan waktu
  inference MediaPipe yang memang tetap sama secara total; penghematan utama
  dari decode H.264 + seek keyframe yang sangat mahal).

Skor yang dihasilkan identik secara formula dengan analyzer-analyzer lama.
Flag USE_VIDEO_VISION_PASS (default True) di settings.py memungkinkan A/B
comparison dengan jalur lama kapan saja.

Kontrak output: dict[str, AnalysisResult] — key adalah analyzer_type string.
"""

import logging
import math
from dataclasses import dataclass, field

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker,
    FaceLandmarkerOptions,
    HandLandmarker,
    HandLandmarkerOptions,
)

from app.ai_modules.base.analyzer_interface import AnalysisResult, AnalyzerUnavailable
from app.ai_modules.cv_models import ensure_model

logger = logging.getLogger(__name__)

# ── Konstanta mirror dari masing-masing analyzer lama ────────────────────────

_MAX_FRAMES = 300

# face_emotion (face_emotion_analyzer.py)
_FACE_LEFT_EYE  = [33, 160, 158, 133, 153, 144]
_FACE_RIGHT_EYE = [362, 385, 387, 263, 373, 380]
_FACE_MOUTH     = [61, 39, 0, 269, 291, 181]
_FACE_MAR_DENOM = 0.35
_FACE_EAR_DENOM = 0.22

# eye_contact (eye_contact_analyzer.py)
_EC_NOSE_TIP    = 1
_EC_EAR_OPEN    = 0.22
_EC_NOSE_OFFSET = 0.25

# gesture (gesture_analyzer.py)
_GESTURE_MOTION_THRESHOLD = 0.01

# scene (scene_change_analyzer.py)
_SCENE_CHANGE_THRESHOLD = 0.12
_SCENE_TARGET_RATIO     = 0.15

# ── Accumulator per-window ────────────────────────────────────────────────────

@dataclass
class _FaceState:
    """Akumulasi data face_emotion + eye_contact dari satu window."""
    frames: int = 0
    face_frames: int = 0
    mar_sum: float = 0.0
    ear_sum: float = 0.0            # dipakai face_emotion
    ear_sum_ec: float = 0.0         # dipakai eye_contact (sama, tapi akumulator terpisah)
    front_frames: int = 0           # eye_contact: kepala menghadap kamera


@dataclass
class _HandState:
    """Akumulasi data gesture dari satu window."""
    frames: int = 0
    hand_frames: int = 0
    motion_sum: float = 0.0
    motion_frames: int = 0
    prev_landmarks: list | None = field(default=None, repr=False)


@dataclass
class _SceneState:
    """Akumulasi data scene_change dari satu window."""
    frames: int = 0
    scene_changes: int = 0
    diff_sum: float = 0.0
    diff_frames: int = 0
    prev_gray: object = field(default=None, repr=False)   # numpy array


# ── Helper fungsi aspect-ratio (identik dengan semua analyzer lama) ───────────

def _aspect_ratio(landmarks, indices: list[int]) -> float:
    """Hitung aspect ratio dari 6 landmark (vert1+vert2) / (2*horiz)."""
    x1, y1 = landmarks[indices[0]].x, landmarks[indices[0]].y
    x2, y2 = landmarks[indices[1]].x, landmarks[indices[1]].y
    x3, y3 = landmarks[indices[2]].x, landmarks[indices[2]].y
    x4, y4 = landmarks[indices[3]].x, landmarks[indices[3]].y
    x5, y5 = landmarks[indices[4]].x, landmarks[indices[4]].y
    x6, y6 = landmarks[indices[5]].x, landmarks[indices[5]].y
    vert1 = math.dist((x2, y2), (x6, y6))
    vert2 = math.dist((x3, y3), (x5, y5))
    horiz = math.dist((x1, y1), (x4, y4))
    if horiz == 0:
        return 0.0
    return (vert1 + vert2) / (2 * horiz)


# ── Fungsi agregasi skor (identik dengan formula analyzer lama) ───────────────

def _score_face_emotion(s: _FaceState) -> AnalysisResult:
    if s.frames == 0 or s.face_frames == 0:
        return AnalysisResult(
            score=5.0,
            result_data={"reason": "Tidak ada wajah terdeteksi dalam window"},
        )
    avg_mar = s.mar_sum / s.face_frames
    avg_ear = s.ear_sum / s.face_frames
    face_ratio = s.face_frames / s.frames

    smile_score  = min(avg_mar / _FACE_MAR_DENOM, 1.0) * 4.0
    eye_score    = min(avg_ear / _FACE_EAR_DENOM, 1.0) * 3.0
    engage_score = face_ratio * 3.0
    final = round(min(5.0 + smile_score + eye_score + engage_score, 10.0), 2)

    return AnalysisResult(
        score=final,
        result_data={
            "reason": "Ekspresi wajah dari MediaPipe FaceMesh (smile + eye contact + engagement)",
            "avg_mouth_aspect_ratio": round(avg_mar, 4),
            "avg_eye_aspect_ratio": round(avg_ear, 4),
            "frames_analyzed": s.frames,
            "frames_with_face": s.face_frames,
            "smile_component": round(smile_score, 2),
            "eye_contact_component": round(eye_score, 2),
            "engagement_component": round(engage_score, 2),
        },
    )


def _score_eye_contact(s: _FaceState) -> AnalysisResult:
    if s.frames == 0 or s.face_frames == 0:
        return AnalysisResult(
            score=5.0,
            result_data={"reason": "Tidak ada wajah terdeteksi dalam window"},
        )
    avg_ear = s.ear_sum_ec / s.face_frames
    eye_open_ratio = min(avg_ear / _EC_EAR_OPEN, 1.0)
    front_ratio = s.front_frames / s.face_frames
    final = round(min(5.0 + eye_open_ratio * 3.0 + front_ratio * 2.0, 10.0), 2)

    return AnalysisResult(
        score=final,
        result_data={
            "reason": "Eye contact dari MediaPipe FaceMesh (mata terbuka + arah kepala)",
            "avg_eye_aspect_ratio": round(avg_ear, 4),
            "front_facing_ratio": round(front_ratio, 3),
            "frames_analyzed": s.frames,
            "frames_with_face": s.face_frames,
        },
    )


def _score_gesture(s: _HandState) -> AnalysisResult:
    if s.frames == 0 or s.hand_frames == 0:
        return AnalysisResult(
            score=5.0,
            result_data={"reason": "Tidak ada tangan terdeteksi dalam window"},
        )
    avg_motion = s.motion_sum / max(s.motion_frames, 1)
    presence_score = min(s.hand_frames / s.frames / 0.6, 1.0)
    motion_score   = min(avg_motion / _GESTURE_MOTION_THRESHOLD, 1.0)
    final = round(min(5.0 + presence_score * 3.0 + motion_score * 2.0, 10.0), 2)

    return AnalysisResult(
        score=final,
        result_data={
            "reason": "Gestur tangan dari MediaPipe Hands (presensi + gerakan)",
            "frames_analyzed": s.frames,
            "frames_with_hands": s.hand_frames,
            "avg_hand_motion": round(avg_motion, 5),
            "hand_presence_ratio": round(s.hand_frames / s.frames, 3),
        },
    )


def _score_scene(s: _SceneState) -> AnalysisResult:
    if s.frames < 2:
        return AnalysisResult(
            score=5.0,
            result_data={"reason": "Terlalu sedikit frame untuk analisis scene"},
        )
    change_ratio = s.scene_changes / max(s.frames - 1, 1)
    avg_diff = s.diff_sum / max(s.diff_frames, 1)
    proximity = 1.0 - min(abs(change_ratio - _SCENE_TARGET_RATIO) / _SCENE_TARGET_RATIO, 1.0)
    motion    = min(avg_diff / _SCENE_CHANGE_THRESHOLD, 1.0)
    final = round(min(5.0 + proximity * 3.0 + motion * 2.0, 10.0), 2)

    return AnalysisResult(
        score=final,
        result_data={
            "reason": "Dinamika scene dari OpenCV frame differencing",
            "scene_changes": s.scene_changes,
            "change_ratio": round(change_ratio, 3),
            "avg_frame_diff": round(avg_diff, 4),
            "frames_analyzed": s.frames,
        },
    )


# ── VideoVisionPass ───────────────────────────────────────────────────────────

class VideoVisionPass:
    """Single-pass decoder untuk 4 analyzer visual.

    Satu instance per job — model MediaPipe di-build sekali saat pertama kali
    analyze_window() dipanggil, lalu di-reuse lintas semua window.

    Usage:
        vvp = VideoVisionPass()
        results: dict[str, AnalysisResult] = vvp.analyze_window(
            video_path, start, end
        )
        # results keys: "face_emotion", "eye_contact", "gesture", "scene"
    """

    def __init__(self) -> None:
        self._face_landmarker: FaceLandmarker | None = None
        self._hand_landmarker: HandLandmarker | None = None

    # ── model init (lazy, cached per instance) ────────────────────────────────

    def _get_face_landmarker(self) -> FaceLandmarker:
        if self._face_landmarker is None:
            model_path = ensure_model("face_landmarker")
            self._face_landmarker = FaceLandmarker.create_from_options(
                FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(model_path)),
                    num_faces=1,
                    min_face_detection_confidence=0.5,
                    min_face_presence_confidence=0.5,
                )
            )
        return self._face_landmarker

    def _get_hand_landmarker(self) -> HandLandmarker:
        if self._hand_landmarker is None:
            model_path = ensure_model("hand_landmarker")
            self._hand_landmarker = HandLandmarker.create_from_options(
                HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(model_path)),
                    num_hands=2,
                    min_hand_detection_confidence=0.5,
                    min_hand_presence_confidence=0.5,
                )
            )
        return self._hand_landmarker

    # ── main API ──────────────────────────────────────────────────────────────

    def analyze_window(
        self,
        video_path: str,
        start: float,
        end: float,
    ) -> dict[str, AnalysisResult]:
        """Decode video window SEKALI, return hasil 4 analyzer.

        Raises AnalyzerUnavailable kalau video tidak bisa dibuka.
        """
        if not video_path:
            raise AnalyzerUnavailable("video_path kosong")

        face_lm = self._get_face_landmarker()
        hand_lm = self._get_hand_landmarker()

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise AnalyzerUnavailable(f"Tidak bisa buka video: {video_path}")

        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        max_frames = min(
            _MAX_FRAMES,
            int((end - start) * fps) if end > start else _MAX_FRAMES,
        )

        face_state  = _FaceState()
        hand_state  = _HandState()
        scene_state = _SceneState()

        try:
            while face_state.frames < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break

                # ── face_emotion + eye_contact (satu FaceLandmarker.detect) ──
                face_state.frames += 1
                hand_state.frames += 1
                scene_state.frames += 1

                rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                # FaceLandmarker — satu inference untuk dua analyzer
                face_result = face_lm.detect(image)
                if face_result.face_landmarks:
                    face_state.face_frames += 1
                    lm = face_result.face_landmarks[0]

                    # face_emotion: MAR + EAR
                    mar = _aspect_ratio(lm, _FACE_MOUTH)
                    ear = (
                        _aspect_ratio(lm, _FACE_LEFT_EYE)
                        + _aspect_ratio(lm, _FACE_RIGHT_EYE)
                    ) / 2
                    face_state.mar_sum += mar
                    face_state.ear_sum += ear

                    # eye_contact: EAR (sama) + nose heading
                    face_state.ear_sum_ec += ear
                    nose = lm[_EC_NOSE_TIP]
                    if (
                        abs(nose.x - 0.5) < _EC_NOSE_OFFSET
                        and abs(nose.y - 0.5) < _EC_NOSE_OFFSET
                    ):
                        face_state.front_frames += 1

                # HandLandmarker
                hand_result = hand_lm.detect(image)
                if hand_result.hand_landmarks:
                    hand_state.hand_frames += 1
                    lm_hand = hand_result.hand_landmarks[0]
                    pts = [(p.x, p.y) for p in lm_hand]

                    if hand_state.prev_landmarks is not None:
                        motion = sum(
                            abs(a[0] - b[0]) + abs(a[1] - b[1])
                            for a, b in zip(pts, hand_state.prev_landmarks)
                        ) / len(pts)
                        hand_state.motion_sum    += motion
                        hand_state.motion_frames += 1

                    hand_state.prev_landmarks = pts
                else:
                    hand_state.prev_landmarks = None

                # Scene (grayscale diff — tidak butuh MediaPipe)
                gray       = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray_small = cv2.resize(gray, (160, 90))

                if scene_state.prev_gray is not None:
                    diff = float(
                        cv2.absdiff(gray_small, scene_state.prev_gray).mean() / 255.0
                    )
                    scene_state.diff_sum    += diff
                    scene_state.diff_frames += 1
                    if diff > _SCENE_CHANGE_THRESHOLD:
                        scene_state.scene_changes += 1

                scene_state.prev_gray = gray_small

        finally:
            cap.release()

        logger.debug(
            "VideoVisionPass window [%.1f-%.1f]: %d frames, %d face, %d hand",
            start, end,
            face_state.frames, face_state.face_frames, hand_state.hand_frames,
        )

        return {
            "face_emotion": _score_face_emotion(face_state),
            "eye_contact":  _score_eye_contact(face_state),
            "gesture":      _score_gesture(hand_state),
            "scene":        _score_scene(scene_state),
        }
