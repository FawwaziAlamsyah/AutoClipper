"""Clip generation service (final FFmpeg render)."""

import logging
import subprocess
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.models.clip_model import ClipModel
from app.repositories.clip_repository import ClipRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.transcript_repository import (
    TranscriptRepository,
    TranscriptSegmentRepository,
)
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
        self.transcript_repo = TranscriptRepository(db)
        self.segment_repo = TranscriptSegmentRepository(db)
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
        """Generate a final clip using FFmpeg from a candidate.

        Setelah _extract_clip() sukses, jalankan Auto Hook Engine (jika aktif):
        - Cari momen hook via LLM (HookMomentFinder)
        - Simpan hasil ke candidate.hook_* untuk ditampilkan di tab Hook UI
        - Render cold-open teaser + concat via HookComposerService
        Kegagalan hook engine TIDAK menggagalkan generate_clip.
        """
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValidationException(f"Candidate {candidate_id} not found")

        video = self.video_repo.get(candidate.video_id)
        if video is None:
            raise ValidationException(f"Video {candidate.video_id} not found")

        if video.is_archived or not Path(video.file_path).exists():
            raise ValidationException(
                f"Video dengan ID {video.id} sudah dihapus. "
                "Tidak bisa generate clip baru dari video ini — data candidate "
                "tetap tersimpan untuk training, tapi file sumbernya sudah tidak ada."
            )

        # ── Render clip biasa ─────────────────────────────────────────────────
        unique_id = str(uuid.uuid4())[:8]
        output_dir = Path("data/outputs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"clip_{video.id}_{candidate.id}_{unique_id}.mp4"

        job_id = candidate.job_id
        logger.debug("Generate process: render clip untuk candidate %d (%s)", candidate_id, aspect_ratio)
        self.job_service.start_optional_step(job_id, "generate")
        try:
            self._extract_clip(
                video.file_path, str(output_path),
                candidate.start_time, candidate.end_time,
                aspect_ratio,
            )
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

        # ── Auto Hook Engine (best-effort, TIDAK boleh raise) ─────────────────
        if settings.USE_AUTO_HOOK:
            self._run_auto_hook(clip, candidate, video)

        # ── Update candidate + history ────────────────────────────────────────
        self.candidate_repo.update_status(candidate_id, "selected")
        self.history_service.log(
            action="clip_exported",
            description=f"Clip {clip.id} exported: {aspect_ratio}",
            video_id=candidate.video_id,
            job_id=candidate.job_id,
        )

        logger.info("Generated clip %d for candidate %d", clip.id, candidate_id)
        return clip

    def _run_auto_hook(self, clip: ClipModel, candidate, video) -> None:
        """Cari momen hook via LLM, simpan ke candidate, lalu compose clip.

        Semua exception di-catch di sini — generate_clip tidak boleh gagal karena hook.
        """
        try:
            from app.ai_modules.hook_analysis.hook_moment_finder import HookMomentFinder
            from app.services.hook_composer_service import HookComposerService

            window_duration = candidate.end_time - candidate.start_time

            # Ambil segments transcript
            transcript = self.transcript_repo.get_by_video(video.id)
            if not transcript:
                logger.debug("Auto Hook skip candidate %d: tidak ada transcript", candidate.id)
                clip.hook_skip_reason = "llm_unavailable"
                self.db.commit()
                return

            segments = self.segment_repo.get_by_transcript(transcript.id)
            # Filter ke window candidate saja
            segs_in_window = [
                s for s in segments
                if s.end_time > candidate.start_time and s.start_time < candidate.end_time
            ]

            # Cari nama kategori untuk konteks LLM
            category_name = candidate.category.name if candidate.category else None

            finder = HookMomentFinder()
            hook_moment, skip_reason = finder.find(segs_in_window, category_name)

            if hook_moment is None:
                logger.info(
                    "Auto Hook skip candidate %d: %s (segments in window: %d, api_key_set: %s)",
                    candidate.id, skip_reason, len(segs_in_window), bool(finder.api_key),
                )
                clip.hook_skip_reason = skip_reason
                self.db.commit()
                return

            # Simpan hasil ke candidate (untuk ditampilkan di tab Hook UI)
            candidate.hook_moment_start = hook_moment.hook_moment_start
            candidate.hook_moment_end   = hook_moment.hook_moment_end
            candidate.hook_type         = hook_moment.hook_type
            candidate.hook_confidence   = hook_moment.hook_confidence
            candidate.hook_caption      = hook_moment.hook_caption
            self.db.commit()

            # Compose cold-open
            composer = HookComposerService(self.db)
            composer.compose(
                clip_id=clip.id,
                video_source_path=video.file_path,
                aspect_ratio=clip.aspect_ratio,
                hook_moment=hook_moment,
                window_duration=window_duration,
            )

        except Exception as e:
            logger.warning(
                "Auto Hook Engine gagal untuk clip %d (clip normal tetap dipakai): %s",
                clip.id, e,
            )
            try:
                clip.hook_skip_reason = "render_failed"
                self.db.commit()
            except Exception:
                pass

    def regenerate_hook(self, clip_id: int) -> ClipModel:
        """Render ulang hook dari momen tersimpan candidate (tanpa replay LLM).

        Dipakai tombol "Generate Ulang Hook" di UI saat render sebelumnya gagal
        (hook_skip_reason=render_failed) atau user coba lagi. Re-uses momen hook
        yang sudah tersimpan di candidate; langsung compose tanpa LLM call.
        """
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise ValidationException(f"Clip {clip_id} not found")

        candidate = self.candidate_repo.get(clip.candidate_id)
        if candidate is None or candidate.hook_moment_start is None:
            raise ValidationException(
                "Tidak ada momen hook tersimpan untuk clip ini — generate ulang via 'Generate Clip'."
            )

        video = self.video_repo.get(candidate.video_id)
        if video is None or not Path(video.file_path).exists():
            raise ValidationException("Video sumber sudah tidak ada.")

        from app.ai_modules.hook_analysis.hook_moment_finder import HookMoment
        from app.services.hook_composer_service import HookComposerService

        hook_moment = HookMoment(
            hook_moment_start=candidate.hook_moment_start,
            hook_moment_end=candidate.hook_moment_end,
            hook_type=candidate.hook_type or "hook",
            hook_confidence=candidate.hook_confidence or 0.0,
            hook_caption=candidate.hook_caption or "",
            best_idx=0,
        )

        composer = HookComposerService(self.db)
        window_duration = candidate.end_time - candidate.start_time
        composer.regenerate_from_candidate(
            clip_id=clip.id,
            video_source_path=video.file_path,
            aspect_ratio=clip.aspect_ratio,
            hook_moment=hook_moment,
            window_duration=window_duration,
        )
        clip = self.clip_repo.get(clip_id)
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
