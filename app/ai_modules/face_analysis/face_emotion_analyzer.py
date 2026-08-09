"""Real face emotion analyzer (OpenCV + MediaPipe Tasks FaceLandmarker).

Deteksi ekspresi dari frame video:
- Smile: mouth aspect ratio (MAR) — mulut terbuka lebar.
- Eye contact: left/right eye aspect ratio (EAR) — mata terbuka (tidak terpejam).
- Engagement (proxy): fraksi frame dengan wajah terdeteksi + kedekatan relatif.

Nilai dirata-ratakan lintas frame window [start, end] → skor 0-10.
MediaPipe Tasks API (model .tflite di-download via cv_models.ensure_model).
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

# Indeks landmark MediaPipe FaceMesh
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]
_MOUTH = [61, 39, 0, 269, 291, 181]  # inner lips

_MAX_FRAMES = 300  # cap analisis (≈10s @ 30fps) agar pipeline tidak lambat


@register_analyzer
class FaceEmotionAnalyzer(AnalyzerInterface):
    """Analisis emosi wajah dari video window."""

    analyzer_type = "face_emotion"

    def __init__(self) -> None:
        """Lazy cache FaceLandmarker — dibuat sekali per job, bukan per window."""
        self._landmarker = None

    def _get_landmarker(self) -> FaceLandmarker:
        """Build FaceLandmarker sekali; reuse lintas window (hemat load model)."""
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
        """Analisis window video.

        input: {"video_path": str, "start": float, "end": float}.
        """
        video_path = input.get("video_path", "")
        start = float(input.get("start", 0.0))
        end = float(input.get("end", 0.0))

        if not video_path:
            raise AnalyzerUnavailable("video_path kosong")

        face_landmarker = self._get_landmarker()

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise AnalyzerUnavailable(f"Tidak bisa buka video: {video_path}")

            # Seek ke start
            cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            max_frames = min(_MAX_FRAMES, int((end - start) * fps) if end > start else _MAX_FRAMES)

            mar_sum = 0.0
            ear_sum = 0.0
            face_frames = 0
            frames = 0

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
                mar = self._aspect_ratio(lm, _MOUTH)
                ear = (self._aspect_ratio(lm, _LEFT_EYE) + self._aspect_ratio(lm, _RIGHT_EYE)) / 2
                mar_sum += mar
                ear_sum += ear

            cap.release()
        except Exception as e:
            if not isinstance(e, AnalyzerUnavailable):
                logger.warning("Face analysis gagal: %s", e)
                raise AnalyzerUnavailable(f"Face analysis error: {e}")
            raise

        if frames == 0 or face_frames == 0:
            return AnalysisResult(
                score=5.0,
                result_data={"reason": "Tidak ada wajah terdeteksi dalam window"},
            )

        avg_mar = mar_sum / face_frames
        avg_ear = ear_sum / face_frames
        face_ratio = face_frames / frames

        # Skor 0-10: smile + eye-open + engagement
        smile_score = min(avg_mar / 0.35, 1.0) * 4.0     # MAR tinggi = senyum
        eye_score = min(avg_ear / 0.22, 1.0) * 3.0       # EAR tinggi = mata terbuka
        engage_score = face_ratio * 3.0                  # wajah hadir di banyak frame

        final = round(min(5.0 + smile_score + eye_score + engage_score, 10.0), 2)
        return AnalysisResult(
            score=final,
            result_data={
                "reason": "Ekspresi wajah dari MediaPipe FaceMesh (smile + eye contact + engagement)",
                "avg_mouth_aspect_ratio": round(avg_mar, 4),
                "avg_eye_aspect_ratio": round(avg_ear, 4),
                "frames_analyzed": frames,
                "frames_with_face": face_frames,
                "smile_component": round(smile_score, 2),
                "eye_contact_component": round(eye_score, 2),
                "engagement_component": round(engage_score, 2),
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
