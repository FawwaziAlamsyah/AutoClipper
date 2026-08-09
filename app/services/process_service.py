"""Video processing pipeline: transcribe → analyze → candidate clips."""

import logging

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException
from app.models.candidate_model import Candidate
from app.models.history_model import History
from app.repositories.video_repository import VideoRepository
from app.services.analysis_service import AnalysisService
from app.services.ffmpeg_service import FFmpegService
from app.services.job_service import JobService
from app.services.transcript_service import TranscriptService

logger = logging.getLogger(__name__)


class ProcessService:
    """Run the full pipeline for an uploaded video: extract → transcribe → analyze → candidates."""

    def __init__(
        self,
        db: Session,
        ffmpeg: FFmpegService | None = None,
        transcript_service: TranscriptService | None = None,
        analysis_service: AnalysisService | None = None,
    ) -> None:
        """Initialize service dependencies (injectable for tests)."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.job_service = JobService(db)
        self.transcript_service = transcript_service or TranscriptService(db, ffmpeg=ffmpeg)
        self.analysis_service = analysis_service or AnalysisService(db)

    def create_job(self, video_id: int) -> int:
        """Create a pipeline job and return its ID (for async processing)."""
        video = self.video_repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")
        job = self.job_service.create(video_id)
        return job.id

    def process_video(
        self,
        video_id: int,
        job_id: int | None = None,
        num_clips: int | None = None,
        keywords: list[str] | None = None,
        skip_keywords: list[str] | None = None,
        language: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        analyze_start_time: float | None = None,
        analyze_end_time: float | None = None,
    ) -> dict:
        """Run pipeline and return generated candidates with real scores."""
        video = self.video_repo.get(video_id)
        if video is None:
            raise NotFoundException(f"Video {video_id} tidak ditemukan")

        num = num_clips or settings.DEFAULT_NUM_CLIPS
        job = self.job_service.get(job_id) if job_id else self.job_service.create(video_id)

        self.job_service.start_step(job.id, "extract")
        self._update_video_metadata(video)
        self.job_service.finish_step(job.id, "extract", success=True)
        self._ensure_not_cancelled(job.id)

        self.job_service.start_step(job.id, "transcribe")
        transcript = self.transcript_service.transcribe(video_id, job_id=job.id, language=language)
        self.job_service.finish_step(job.id, "transcribe", success=True)
        self._ensure_not_cancelled(job.id)

        self.job_service.start_step(job.id, "analyze")
        candidates = self.analysis_service.analyze_job(
            job.id,
            video_id,
            transcript,
            num_clips=num,
            keywords=keywords or [],
            skip_keywords=skip_keywords or [],
            min_duration=min_duration,
            max_duration=max_duration,
            analyze_start_time=analyze_start_time,
            analyze_end_time=analyze_end_time,
        )
        self.job_service.finish_step(job.id, "analyze", success=True)

        if not candidates:
            self.job_service.finish_step(job.id, "analyze", success=False, error="Tidak ada segmen transcript")
            raise NotFoundException("Tidak ada segmen transcript untuk dibuat candidate")

        self.job_service.complete_job(job.id)

        video.status = "ready"
        self.db.add(History(
            video_id=video_id,
            job_id=job.id,
            action="candidate_generated",
            description=f"Generated {len(candidates)} candidate clips dari transcript",
        ))
        self.db.commit()

        return {
            "video_id": video_id,
            "job_id": job.id,
            "candidates": [
                {
                    "id": c.id,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "final_score": c.final_score,
                    "hook_text": c.hook_text,
                    "status": c.status,
                    "score_breakdown": c.score_breakdown or {},
                }
                for c in candidates
            ],
        }

    def _ensure_not_cancelled(self, job_id: int) -> None:
        """Raise if job was cancelled by user."""
        job = self.job_service.get(job_id)
        if job.status == "cancelled":
            raise InterruptedError(f"Job {job_id} dibatalkan oleh user")

    def _update_video_metadata(self, video) -> None:
        """Update metadata using ffprobe."""
        try:
            meta = self.transcript_service.ffmpeg.extract_metadata(video.file_path)
            video.duration_seconds = meta.get("duration_seconds")
            video.width = meta.get("width")
            video.height = meta.get("height")
            video.fps = meta.get("fps")
            video.status = "processing"
            self.db.commit()
        except Exception as e:
            logger.warning("Metadata extraction failed: %s", e)
