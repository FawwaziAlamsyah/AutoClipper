"""Gesture analyzer (OpenCV + MediaPipe Tasks HandLandmarker).

Deteksi gestur aktif: jumlah tangan terdeteksi + pergerakan landmark antar-frame.
Tangan terdeteksi + bergerak = gestur aktif; diam/tiada = netral.
"""

import logging

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions

from app.ai_modules.base.analyzer_interface import (
    AnalysisResult,
    AnalyzerInterface,
    AnalyzerUnavailable,
)
from app.ai_modules.cv_models import ensure_model
from app.ai_modules.registry import register_analyzer

logger = logging.getLogger(__name__)

_MAX_FRAMES = 300
_MOTION_THRESHOLD = 0.01  # perubahan posisi landmark (normalized)


@register_analyzer
class GestureAnalyzer(AnalyzerInterface):
    """Skor aktivitas gestur tangan dari video window."""

    analyzer_type = "gesture"

    def __init__(self) -> None:
        """Lazy cache HandLandmarker — dibuat sekali per job, bukan per window."""
        self._hands = None

    def _get_hands(self) -> HandLandmarker:
        """Build HandLandmarker sekali; reuse lintas window."""
        if self._hands is None:
            model_path = ensure_model("hand_landmarker")
            self._hands = HandLandmarker.create_from_options(
                HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(model_path)),
                    num_hands=2,
                    min_hand_detection_confidence=0.5,
                    min_hand_presence_confidence=0.5,
                )
            )
        return self._hands

    def analyze(self, input: dict) -> AnalysisResult:
        """Analisis gestur window video.

        input: {"video_path": str, "start": float, "end": float}.
        """
        video_path = input.get("video_path", "")
        start = float(input.get("start", 0.0))
        end = float(input.get("end", 0.0))

        if not video_path:
            raise AnalyzerUnavailable("video_path kosong")

        hands = self._get_hands()

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise AnalyzerUnavailable(f"Tidak bisa buka video: {video_path}")

        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        max_frames = min(_MAX_FRAMES, int((end - start) * fps) if end > start else _MAX_FRAMES)

        hand_frames = 0
        motion_sum = 0.0
        motion_frames = 0
        frames = 0
        prev_landmarks = None

        try:
            while frames < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                frames += 1

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                results = hands.detect(image)

                if results.hand_landmarks:
                    hand_frames += 1
                    lm = results.hand_landmarks[0]
                    pts = [(p.x, p.y) for p in lm]

                    if prev_landmarks is not None:
                        motion = sum(
                            abs(a[0] - b[0]) + abs(a[1] - b[1])
                            for a, b in zip(pts, prev_landmarks)
                        ) / len(pts)
                        motion_sum += motion
                        motion_frames += 1

                    prev_landmarks = pts
                else:
                    prev_landmarks = None
        finally:
            cap.release()

        if frames == 0 or hand_frames == 0:
            return AnalysisResult(
                score=5.0,
                result_data={"reason": "Tidak ada tangan terdeteksi dalam window"},
            )

        avg_motion = motion_sum / max(motion_frames, 1)

        presence_score = min(hand_frames / frames / 0.6, 1.0)   # tangan hadir di sebagian besar frame
        motion_score = min(avg_motion / _MOTION_THRESHOLD, 1.0)  # gerakan aktif

        final = round(min(5.0 + presence_score * 3.0 + motion_score * 2.0, 10.0), 2)

        return AnalysisResult(
            score=final,
            result_data={
                "reason": "Gestur tangan dari MediaPipe Hands (presensi + gerakan)",
                "frames_analyzed": frames,
                "frames_with_hands": hand_frames,
                "avg_hand_motion": round(avg_motion, 5),
                "hand_presence_ratio": round(hand_frames / frames, 3),
            },
        )
