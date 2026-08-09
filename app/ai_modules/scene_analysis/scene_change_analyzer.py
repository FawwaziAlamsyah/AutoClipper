"""Scene change analyzer (OpenCV frame differencing).

Deteksi perubahan scene via mean abs diff antar-frame. Perubahan scene moderat
= dinamis menarik; terlalu banyak (chaotic) atau terlalu sedikit (statis) = rendah.
"""

import logging

import cv2

from app.ai_modules.base.analyzer_interface import (
    AnalysisResult,
    AnalyzerInterface,
    AnalyzerUnavailable,
)
from app.ai_modules.registry import register_analyzer

logger = logging.getLogger(__name__)

_MAX_FRAMES = 300
_SCENE_CHANGE_THRESHOLD = 0.12  # mean abs diff normalisasi
_TARGET_RATIO = 0.15  # ~15% frame adalah scene change = ideal dinamis


@register_analyzer
class SceneChangeAnalyzer(AnalyzerInterface):
    """Skor dinamika scene dari video window."""

    analyzer_type = "scene"

    def analyze(self, input: dict) -> AnalysisResult:
        """Analisis scene change window video.

        input: {"video_path": str, "start": float, "end": float}.
        """
        video_path = input.get("video_path", "")
        start = float(input.get("start", 0.0))
        end = float(input.get("end", 0.0))

        if not video_path:
            raise AnalyzerUnavailable("video_path kosong")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise AnalyzerUnavailable(f"Tidak bisa buka video: {video_path}")

        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        max_frames = min(_MAX_FRAMES, int((end - start) * fps) if end > start else _MAX_FRAMES)

        frames = 0
        scene_changes = 0
        diff_sum = 0.0
        diff_frames = 0
        prev_gray = None

        try:
            while frames < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                frames += 1

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (160, 90))  # downscale untuk kecepatan

                if prev_gray is not None:
                    diff = float(cv2.absdiff(gray, prev_gray).mean() / 255.0)
                    diff_sum += diff
                    diff_frames += 1
                    if diff > _SCENE_CHANGE_THRESHOLD:
                        scene_changes += 1

                prev_gray = gray
        finally:
            cap.release()

        if frames < 2:
            return AnalysisResult(
                score=5.0,
                result_data={"reason": "Terlalu sedikit frame untuk analisis scene"},
            )

        change_ratio = scene_changes / max(frames - 1, 1)
        avg_diff = diff_sum / max(diff_frames, 1)

        # Skor: perubahan scene mendekati target ideal, tapi frame harus bergerak
        proximity = 1.0 - min(abs(change_ratio - _TARGET_RATIO) / _TARGET_RATIO, 1.0)
        motion = min(avg_diff / _SCENE_CHANGE_THRESHOLD, 1.0)

        final = round(min(5.0 + proximity * 3.0 + motion * 2.0, 10.0), 2)

        return AnalysisResult(
            score=final,
            result_data={
                "reason": "Dinamika scene dari OpenCV frame differencing",
                "scene_changes": scene_changes,
                "change_ratio": round(change_ratio, 3),
                "avg_frame_diff": round(avg_diff, 4),
                "frames_analyzed": frames,
            },
        )
