"""Facecam Detector Service — AI-based 4-Corner Facecam Scanner for Gaming Streams.

Mendeteksi posisi webcam streamer di 4 sudut video:
- bottom_left (bawah kiri)
- bottom_right (bawah kanan)
- top_left (atas kiri)
- top_right (atas kanan)
- none (tidak ada webcam / gameplay murni)

Hasil pemindaian disimpan di cache per-video agar proses generasi klip instan.
"""

import logging
from pathlib import Path
from typing import Literal

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions

from app.ai_modules.cv_models import ensure_model

logger = logging.getLogger(__name__)

FacecamPosition = Literal["bottom_left", "bottom_right", "top_left", "top_right", "none"]

# Cache in-memory per file video: {video_path: {"position": ..., "center": ...}}
_FACECAM_CACHE: dict[str, dict] = {}


class FacecamDetectorService:
    """Service untuk memindai dan mendeteksi posisi facecam pada video gaming."""

    def __init__(self) -> None:
        self._landmarker = None

    def _get_landmarker(self) -> FaceLandmarker | None:
        """Lazy load MediaPipe FaceLandmarker."""
        if self._landmarker is None:
            try:
                model_path = ensure_model("face_landmarker")
                self._landmarker = FaceLandmarker.create_from_options(
                    FaceLandmarkerOptions(
                        base_options=BaseOptions(model_asset_path=str(model_path)),
                        num_faces=1,
                        min_face_detection_confidence=0.35,
                        min_face_presence_confidence=0.35,
                    )
                )
            except Exception as e:
                logger.warning("Gagal inisialisasi FaceLandmarker untuk FacecamDetector: %s", e)
                return None
        return self._landmarker

    def detect_facecam_position(
        self,
        video_path: str,
        start_time: float = 0.0,
        end_time: float | None = None,
        num_samples: int = 4,
        force_rescan: bool = False,
    ) -> dict:
        """Pindai sudut video untuk mendeteksi posisi webcam streamer.

        Args:
            video_path: Path video sumber
            start_time: Titik awal sampel (detik)
            end_time: Titik akhir sampel (detik, default start_time + 60s)
            num_samples: Jumlah frame yang di-sampling
            force_rescan: Abaikan cache jika True

        Returns:
            dict: {
                "position": "bottom_left" | "bottom_right" | "top_left" | "top_right" | "none",
                "confidence": float,
                "center": (cx, cy) | None,
                "corner_scores": dict,
            }
        """
        video_str = str(Path(video_path).resolve())
        if not force_rescan and video_str in _FACECAM_CACHE:
            cached = _FACECAM_CACHE[video_str]
            logger.debug("FacecamDetector: pakai hasil cache untuk %s -> %s", video_str, cached["position"])
            return cached

        if not Path(video_path).exists():
            fallback = {"position": "bottom_right", "confidence": 0.0, "center": None, "corner_scores": {}}
            return fallback

        landmarker = self._get_landmarker()
        if landmarker is None:
            fallback = {"position": "bottom_right", "confidence": 0.0, "center": None, "corner_scores": {}}
            return fallback

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            fallback = {"position": "bottom_right", "confidence": 0.0, "center": None, "corner_scores": {}}
            return fallback

        try:
            total_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            video_dur = total_frames / total_fps if total_frames > 0 else 60.0

            s_time = max(0.0, start_time)
            e_time = min(video_dur, end_time if end_time is not None else s_time + 60.0)
            if e_time <= s_time:
                e_time = s_time + 10.0

            # Hitung titik waktu sampling
            step = (e_time - s_time) / (num_samples + 1)
            sample_times = [s_time + step * (i + 1) for i in range(num_samples)]

            corner_scores = {
                "bottom_left": 0,
                "bottom_right": 0,
                "top_left": 0,
                "top_right": 0,
            }
            corner_centers: dict[str, list[tuple[float, float]]] = {
                "bottom_left": [],
                "bottom_right": [],
                "top_left": [],
                "top_right": [],
            }

            for t in sample_times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue

                h, w = frame.shape[:2]

                # 4 Sudut kandidat webcam:
                # - BL: x: 0..35%, y: 50%..100%
                # - BR: x: 65%..100%, y: 50%..100%
                # - TL: x: 0..35%, y: 0..50%
                # - TR: x: 65%..100%, y: 0..50%
                corners = {
                    "bottom_left": (frame[int(h * 0.50):, :int(w * 0.35)], 0.0, 0.50, 0.35, 0.50),
                    "bottom_right": (frame[int(h * 0.50):, int(w * 0.65):], 0.65, 0.50, 0.35, 0.50),
                    "top_left": (frame[:int(h * 0.50), :int(w * 0.35)], 0.0, 0.0, 0.35, 0.50),
                    "top_right": (frame[:int(h * 0.50), int(w * 0.65):], 0.65, 0.0, 0.35, 0.50),
                }

                for cname, (cimg, norm_x, norm_y, norm_w, norm_h) in corners.items():
                    if cimg.size == 0:
                        continue
                    try:
                        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(cimg, cv2.COLOR_BGR2RGB))
                        res = landmarker.detect(mp_img)
                        if res.face_landmarks:
                            lms = res.face_landmarks[0]
                            # Normalized face center in full image coordinates (0.0 to 1.0)
                            rel_cx = sum(lm.x for lm in lms) / len(lms)
                            rel_cy = sum(lm.y for lm in lms) / len(lms)
                            full_cx = norm_x + rel_cx * norm_w
                            full_cy = norm_y + rel_cy * norm_h

                            corner_scores[cname] += 1
                            corner_centers[cname].append((full_cx, full_cy))
                    except Exception as e:
                        logger.debug("Face detect corner %s error: %s", cname, e)

            # Tentukan posisi pemenang dengan skor terbanyak
            best_pos = "bottom_right"  # default fallback
            max_hits = 0
            for pos, hits in corner_scores.items():
                if hits > max_hits:
                    max_hits = hits
                    best_pos = pos

            confidence = max_hits / num_samples if num_samples > 0 else 0.0

            # Jika sama sekali tidak ada wajah terdeteksi (gameplay murni tanpa webcam)
            if max_hits == 0:
                result = {
                    "position": "none",
                    "confidence": 0.0,
                    "center": None,
                    "corner_scores": corner_scores,
                }
            else:
                centers = corner_centers[best_pos]
                avg_center = (
                    sum(c[0] for c in centers) / len(centers),
                    sum(c[1] for c in centers) / len(centers),
                )
                result = {
                    "position": best_pos,
                    "confidence": round(confidence, 2),
                    "center": (round(avg_center[0], 3), round(avg_center[1], 3)),
                    "corner_scores": corner_scores,
                }

            _FACECAM_CACHE[video_str] = result
            logger.info("FacecamDetector untuk %s: pos=%s, conf=%.2f, center=%s", Path(video_path).name, result["position"], confidence, result.get("center"))
            return result

        finally:
            cap.release()

    @staticmethod
    def get_facecam_crop_filter(
        position: str = "bottom_right",
        zoom_scale: float = 1.0,
        face_center: tuple[float, float] | list[float] | None = None,
    ) -> str:
        """Kembalikan string filter FFmpeg untuk memotong facecam (1080x800).

        Jika zoom_scale > 1.0 (misal 1.25x untuk punch-zoom), area crop diperkecil
        di sekitar koordinat wajah streamer (face_center) atau titik tengah facecam
        lalu di-scale balik ke 1080x800.
        Posisi:
        - bottom_left: crop pojok kiri bawah
        - bottom_right: crop pojok kanan bawah
        - top_left: crop pojok kiri atas
        - top_right: crop pojok kanan atas
        - none: fallback ke bottom_right
        """
        pos = position.lower()
        scale = max(1.0, min(float(zoom_scale), 2.0))

        # Dimensi dasar facecam
        w0 = 0.30
        h0 = 0.38

        # Posisi sudut dasar (x0, y0)
        if pos == "bottom_left":
            x0_str = "0"
            y0_str = "ih-ih*0.39"
            x_base, y_base = 0.0, 0.61
        elif pos == "top_left":
            x0_str = "0"
            y0_str = "0"
            x_base, y_base = 0.0, 0.0
        elif pos == "top_right":
            x0_str = "iw-iw*0.31"
            y0_str = "0"
            x_base, y_base = 0.69, 0.0
        else:  # "bottom_right" or default
            x0_str = "iw-iw*0.31"
            y0_str = "ih-ih*0.39"
            x_base, y_base = 0.69, 0.61

        if scale <= 1.001:
            return f"[vface]crop=w=iw*{w0:.2f}:h=ih*{h0:.2f}:x={x0_str}:y={y0_str},scale=1080:800:flags=lanczos[top];"

        # Zoomed dimensions
        w_zoom = w0 / scale
        h_zoom = h0 / scale

        # Jika ada koordinat wajah (cx, cy) dari MediaPipe, pusatkan zoom tepat ke wajah
        # dengan tetap di-clamp di dalam batas kotak facecam agar tidak keluar frame
        if face_center and len(face_center) >= 2:
            cx, cy = float(face_center[0]), float(face_center[1])
            x_min, x_max = x_base, x_base + (w0 - w_zoom)
            y_min, y_max = y_base, y_base + (h0 - h_zoom)
            x_target = max(x_min, min(x_max, cx - w_zoom / 2.0))
            y_target = max(y_min, min(y_max, cy - h_zoom / 2.0))
            return (
                f"[vface]crop=w=iw*{w_zoom:.4f}:h=ih*{h_zoom:.4f}:"
                f"x=iw*{x_target:.4f}:y=ih*{y_target:.4f},scale=1080:800:flags=lanczos[top];"
            )

        delta_x = (w0 - w_zoom) / 2.0
        delta_y = (h0 - h_zoom) / 2.0

        if pos == "bottom_left":
            x_expr = f"iw*{delta_x:.4f}"
            y_expr = f"ih-ih*0.39+ih*{delta_y:.4f}"
        elif pos == "top_left":
            x_expr = f"iw*{delta_x:.4f}"
            y_expr = f"ih*{delta_y:.4f}"
        elif pos == "top_right":
            x_expr = f"iw-iw*0.31+iw*{delta_x:.4f}"
            y_expr = f"ih*{delta_y:.4f}"
        else:  # bottom_right
            x_expr = f"iw-iw*0.31+iw*{delta_x:.4f}"
            y_expr = f"ih-ih*0.39+ih*{delta_y:.4f}"

        return f"[vface]crop=w=iw*{w_zoom:.4f}:h=ih*{h_zoom:.4f}:x={x_expr}:y={y_expr},scale=1080:800:flags=lanczos[top];"

