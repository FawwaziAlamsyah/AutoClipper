"""Eye contact analyzer (OpenCV + MediaPipe Tasks FaceLandmarker).

Mata terbuka (EAR tinggi) + kepala menghadap kamera (nose tip dekat pusat frame)
= eye contact aktif.
"""

import logging

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions

from app.ai_modules.base.analyzer_interface import (
    AnalysisResult,
    AnalyzerInterface,
    AnalyzerUnavailable,
)
from app.ai_modules.cv_models import ensure_model
from app.ai_modules.registry import register_analyzer

logger = logging.getLogger(__name__)

_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]
_NOSE_TIP = 1

_MAX_FRAMES = 300
_EAR_OPEN = 0.22  # EAR di atas ini = mata terbuka
_NOSE_OFFSET = 0.25  # nose tip dalam 25% dari pusat = menghadap kamera


@register_analyzer
class EyeContactAnalyzer(AnalyzerInterface):
    """Skor eye contact dari video window."""

    analyzer_type = "eye_contact"

    def __init__(self) -> None:
        """Lazy cache FaceLandmarker — dibuat sekali per job, bukan per window."""
        self._landmarker = None

    def _get_landmarker(self) -> FaceLandmarker:
        """Build FaceLandmarker sekali; reuse lintas window."""
        if self._landmarker is None:
            model_path = ensure_model("face_landmarker")
            self._landmarker = FaceLandmarker.create_from_options(
                FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(model_path)),
                    num_faces=1,
                    min_face_detection_confidence=0.5,
                    min_face_presence_confidence=0.5,
                )
            )
        return self._landmarker

    def analyze(self, input: dict) -> AnalysisResult:
        """Analisis eye contact window video.

        input: {"video_path": str, "start": float, "end": float}.
        """
        video_path = input.get("video_path", "")
        start = float(input.get("start", 0.0))
        end = float(input.get("end", 0.0))

        if not video_path:
            raise AnalyzerUnavailable("video_path kosong")

        face_landmarker = self._get_landmarker()

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise AnalyzerUnavailable(f"Tidak bisa buka video: {video_path}")

        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        max_frames = min(_MAX_FRAMES, int((end - start) * fps) if end > start else _MAX_FRAMES)

        ear_sum = 0.0
        front_frames = 0
        face_frames = 0
        frames = 0

        try:
            while frames < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                frames += 1

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                results = face_landmarker.detect(image)

                if not results.face_landmarks:
                    continue

                face_frames += 1
                lm = results.face_landmarks[0]
                ear = (self._aspect_ratio(lm, _LEFT_EYE) + self._aspect_ratio(lm, _RIGHT_EYE)) / 2
                ear_sum += ear

                nose = lm[_NOSE_TIP]
                if abs(nose.x - 0.5) < _NOSE_OFFSET and abs(nose.y - 0.5) < _NOSE_OFFSET:
                    front_frames += 1
        finally:
            cap.release()

        if frames == 0 or face_frames == 0:
            return AnalysisResult(
                score=5.0,
                result_data={"reason": "Tidak ada wajah terdeteksi dalam window"},
            )

        avg_ear = ear_sum / face_frames
        eye_open_ratio = min(avg_ear / _EAR_OPEN, 1.0)
        front_ratio = front_frames / face_frames

        final = round(min(5.0 + eye_open_ratio * 3.0 + front_ratio * 2.0, 10.0), 2)

        return AnalysisResult(
            score=final,
            result_data={
                "reason": "Eye contact dari MediaPipe FaceMesh (mata terbuka + arah kepala)",
                "avg_eye_aspect_ratio": round(avg_ear, 4),
                "front_facing_ratio": round(front_ratio, 3),
                "frames_analyzed": frames,
                "frames_with_face": face_frames,
            },
        )

    @staticmethod
    def _aspect_ratio(landmarks, indices: list[int]) -> float:
        """Hitung aspect ratio sekumpulan landmark (jarak vertikal / horizontal)."""
        import math

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
