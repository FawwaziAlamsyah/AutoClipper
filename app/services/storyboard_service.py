"""Storyboard service for multimodal AI Video Analysis.

Extracts regular video frames, renders crisp timestamp labels on each frame,
stitches them into 4x4 grid sheets (16 frames per sheet), and returns base64
encoded JPEG data URIs for vision-enabled LLMs (e.g. Gemini 3.8 Flash).
Also detects major scene cut timestamps during extraction without extra passes.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class StoryboardService:
    """Service untuk membuat storyboard grid sheets dari video."""

    def __init__(
        self,
        frame_width: int = 320,
        frame_height: int = 180,
        grid_cols: int = 4,
        grid_rows: int = 4,
        max_total_frames: int = 600,
        target_interval: float = 3.0,
        jpeg_quality: int = 75,
    ) -> None:
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.grid_cols = grid_cols
        self.grid_rows = grid_rows
        self.frames_per_sheet = grid_cols * grid_rows  # 16 frames
        self.max_total_frames = max_total_frames
        self.target_interval = target_interval
        self.jpeg_quality = jpeg_quality

    def generate_storyboard(
        self,
        video_path: str | Path,
    ) -> tuple[list[str], list[float]]:
        """Generate storyboard grid sheets and scene cut timestamps.

        Args:
            video_path: Path file video.

        Returns:
            tuple of:
              - list of data URIs: ["data:image/jpeg;base64,...", ...]
              - list of scene cut timestamps in seconds: [12.4, 35.1, ...]
        """
        path_str = str(video_path)
        cap = cv2.VideoCapture(path_str)
        if not cap.isOpened():
            logger.warning("StoryboardService: Gagal membuka video %s", path_str)
            return [], []

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration = (total_frames_count / fps) if fps > 0 and total_frames_count > 0 else 0.0

            if duration <= 0:
                logger.warning("StoryboardService: Durasi video tidak valid (%s)", path_str)
                return [], []

            # Adaptif interval agar total frame tidak melebihi max_total_frames
            interval = max(self.target_interval, duration / self.max_total_frames)
            frame_step = max(1, int(interval * fps))

            logger.info(
                "StoryboardService: video durasi=%.1fs, fps=%.1f, interval=%.2fs (step=%d frames)",
                duration, fps, interval, frame_step,
            )

            sheets: list[str] = []
            scene_cuts: list[float] = []

            current_sheet_frames: list[np.ndarray] = []
            prev_gray_small: np.ndarray | None = None
            current_frame_idx = 0

            while current_frame_idx < total_frames_count:
                cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_idx)
                ret, frame = cap.read()
                if not ret or frame is None:
                    break

                current_sec = current_frame_idx / fps

                # Deteksi scene change via downscaled difference
                gray_small = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray_small = cv2.resize(gray_small, (80, 45))
                if prev_gray_small is not None:
                    diff = float(cv2.absdiff(gray_small, prev_gray_small).mean() / 255.0)
                    if diff > 0.22:
                        scene_cuts.append(round(current_sec, 2))
                prev_gray_small = gray_small

                # Resize frame ke ukuran thumbnail grid
                thumb = cv2.resize(frame, (self.frame_width, self.frame_height), interpolation=cv2.INTER_AREA)

                # Format timestamp string MM:SS atau HH:MM:SS
                time_str = self._format_timestamp(current_sec)

                # Render background pill + teks timestamp kontras di pojok kiri atas
                self._draw_timestamp_label(thumb, time_str)

                current_sheet_frames.append(thumb)

                # Jika satu sheet 4x4 sudah penuh, rakit dan encode
                if len(current_sheet_frames) == self.frames_per_sheet:
                    sheet_data_uri = self._build_sheet_uri(current_sheet_frames)
                    sheets.append(sheet_data_uri)
                    current_sheet_frames = []

                current_frame_idx += frame_step

            # Rakit sheet sisa terakhir jika ada frame yang tersisa
            if current_sheet_frames:
                sheet_data_uri = self._build_sheet_uri(current_sheet_frames)
                sheets.append(sheet_data_uri)

            logger.info(
                "StoryboardService: Selesai generate %d storyboard sheets, %d scene cuts terdeteksi",
                len(sheets), len(scene_cuts),
            )
            return sheets, scene_cuts

        finally:
            cap.release()

    def _draw_timestamp_label(self, img: np.ndarray, text: str) -> None:
        """Render label timestamp dengan latar belakang gelap kontras di pojok kiri atas."""
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.45
        thickness = 1

        (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
        pad_x, pad_y = 4, 3

        # Kotak hitam semi-transparan sebagai background
        x1, y1 = 4, 4
        x2, y2 = x1 + text_w + (pad_x * 2), y1 + text_h + (pad_y * 2)

        sub_img = img[y1:y2, x1:x2]
        if sub_img.shape[0] > 0 and sub_img.shape[1] > 0:
            black_rect = np.zeros_like(sub_img)
            cv2.addWeighted(black_rect, 0.75, sub_img, 0.25, 0, sub_img)
            img[y1:y2, x1:x2] = sub_img

        # Teks putih tajam
        text_x = x1 + pad_x
        text_y = y1 + text_h + pad_y - 1
        cv2.putText(
            img,
            text,
            (text_x, text_y),
            font,
            scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )

    def _build_sheet_uri(self, frames: list[np.ndarray]) -> str:
        """Stitch list of frames (up to 16) into a 4x4 grid and encode as JPEG data URI."""
        total_slots = self.frames_per_sheet
        padded_frames = list(frames)

        # Pad sisa slot kosong dengan frame hitam jika kurang dari 16
        while len(padded_frames) < total_slots:
            black = np.zeros((self.frame_height, self.frame_width, 3), dtype=np.uint8)
            padded_frames.append(black)

        # Rakit baris per baris
        rows = []
        for r in range(self.grid_rows):
            start_idx = r * self.grid_cols
            end_idx = start_idx + self.grid_cols
            row_img = np.hstack(padded_frames[start_idx:end_idx])
            rows.append(row_img)

        grid_img = np.vstack(rows)

        # Encode ke JPEG
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        success, buffer = cv2.imencode(".jpg", grid_img, encode_params)
        if not success:
            raise RuntimeError("Gagal encode storyboard grid image ke format JPEG")

        b64_str = base64.b64encode(buffer.tobytes()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64_str}"

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format detik ke MM:SS atau HH:MM:SS."""
        total_sec = max(0, int(seconds))
        hours = total_sec // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"
