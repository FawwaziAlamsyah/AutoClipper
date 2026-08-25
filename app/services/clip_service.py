"""Clip generation service (final FFmpeg render)."""

import logging
import subprocess
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions.base import ValidationException
from app.models.clip_model import ClipModel
from app.repositories.clip_repository import ClipRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.video_repository import VideoRepository
from app.services.ffmpeg_service import FFmpegService
from app.services.history_service import HistoryService
from app.services.job_service import JobService

logger = logging.getLogger(__name__)


class ClipService:
    """Generate final clip from candidate using FFmpeg."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session and tool services."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.candidate_repo = CandidateRepository(db)
        self.clip_repo = ClipRepository(db)
        self.ffmpeg = FFmpegService()
        self.history_service = HistoryService(db)
        self.job_service = JobService(db)

    def generate_clip(
        self,
        candidate_id: int,
        aspect_ratio: str = "16:9",
        subtitle_enabled: bool = False,
        subtitle_style: str = "minimal",
    ) -> ClipModel:
        """Generate a final clip using FFmpeg from a candidate."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValidationException(f"Candidate {candidate_id} not found")

        video = self.video_repo.get(candidate.video_id)
        if video is None:
            raise ValidationException(f"Video {candidate.video_id} not found")

        # Cek file masih ada sebelum coba render.
        if video.is_archived or not Path(video.file_path).exists():
            raise ValidationException(
                f"Video dengan ID {video.id} sudah dihapus. "
                "Tidak bisa generate clip baru dari video ini — data candidate "
                "tetap tersimpan untuk training, tapi file sumbernya sudah tidak ada."
            )

        # Generate output filename
        unique_id = str(uuid.uuid4())[:8]
        output_dir = Path("data/outputs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"clip_{video.id}_{candidate.id}_{unique_id}.mp4"

        # Step opsional "generate" — catat job_steps TANPA ubah status job
        # (job sudah completed, tak boleh jadi running lagi).
        job_id = candidate.job_id
        logger.debug("Generate process: render clip untuk candidate %d (%s)", candidate_id, aspect_ratio)
        self.job_service.start_optional_step(job_id, "generate")
        try:
            self._extract_clip(video.file_path, str(output_path), candidate.start_time, candidate.end_time, aspect_ratio)
        except Exception:
            self.job_service.finish_optional_step(job_id, "generate", success=False, error="FFmpeg render gagal")
            logger.debug("Generate process: error - FFmpeg render gagal")
            raise
        self.job_service.finish_optional_step(job_id, "generate", success=True)
        logger.debug("Generate process: success - clip %s", output_path.name)

        clip = ClipModel(
            candidate_id=candidate_id,
            video_id=candidate.video_id,
            file_path=str(output_path),
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            aspect_ratio=aspect_ratio,
            has_subtitle=subtitle_enabled,
            status="completed",
        )
        clip = self.clip_repo.add(clip)

        # Update candidate status via repository
        self.candidate_repo.update_status(candidate_id, "selected")

        # Log to history
        self.history_service.log(
            action="clip_exported",
            description=f"Clip {clip.id} exported: {aspect_ratio}",
            video_id=candidate.video_id,
            job_id=candidate.job_id,
        )

        logger.info("Generated clip %d for candidate %d", clip.id, candidate_id)
        return clip

    def _extract_clip(self, input_path: str, output_path: str, start: float, end: float, aspect_ratio: str) -> None:
        """Extract clip using FFmpeg with reframing for social media output.

        Untuk 9:16 (TikTok/Reels/Shorts): crop tengah dari video sumber supaya
        gambar penuh tanpa pillar-box hitam — standar sosmed.
        Untuk 16:9 dan 1:1: tetap pakai scale+pad (lebih aman untuk konten landscape).
        """
        width, height = self._parse_aspect_ratio(aspect_ratio)
        duration = end - start

        # Video filter: crop tengah untuk 9:16, scale+pad untuk rasio lain
        if aspect_ratio == "9:16":
            # Crop bagian tengah video sumber ke rasio 9:16, lalu scale ke 1080x1920.
            # crop=ih*9/16:ih ambil lebar = tinggi×(9/16), tinggi penuh, dari tengah horizontal.
            # Kalau video sumber sudah portrait atau lebih sempit dari 9:16,
            # fallback ke scale+pad supaya tidak error.
            vf = (
                f"crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9):(iw-min(iw\\,ih*9/16))/2:(ih-min(ih\\,iw*16/9))/2,"
                f"scale={width}:{height}:flags=lanczos"
            )
        else:
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
            )

        cmd = [
            self.ffmpeg.ffmpeg_path,
            "-y",
            "-ss", str(start),
            "-i", input_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "slow",   # slow = kualitas lebih baik, ukuran lebih kecil vs fast
            "-crf", "18",        # 18 = kualitas tinggi (visually lossless), sosmed-ready
            "-c:a", "aac",
            "-b:a", "192k",      # naik dari 128k untuk audio sosmed
            "-movflags", "+faststart",  # progressive download, penting untuk sosmed
            output_path,
        ]

        logger.info("Running FFmpeg: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        if result.returncode != 0:
            logger.error("FFmpeg failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg error: {result.stderr}")

        logger.info("Clip saved: %s", output_path)

    def _parse_aspect_ratio(self, ratio: str) -> tuple[int, int]:
        """Parse aspect ratio string to (width, height)."""
        if ratio == "9:16":
            return (1080, 1920)
        if ratio == "16:9":
            return (1920, 1080)
        if ratio == "1:1":
            return (1080, 1080)
        # Default: 16:9
        return (1920, 1080)
