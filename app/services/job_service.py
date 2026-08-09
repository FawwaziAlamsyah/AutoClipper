"""Job & job step lifecycle management."""

import logging
from datetime import datetime, UTC

from sqlalchemy.orm import Session

from app.core.exceptions.base import NotFoundException
from app.models.job_model import Job
from app.models.job_step_model import JobStep
from app.repositories.job_repository import JobRepository, JobStepRepository

logger = logging.getLogger(__name__)

PIPELINE_STEPS = ("extract", "transcribe", "analyze", "score", "generate", "export")


class JobService:
    """Create and track pipeline jobs."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db
        self.repo = JobRepository(db)
        self.step_repo = JobStepRepository(db)

    def create(self, video_id: int, pipeline_name: str = "auto_clipper_v1") -> Job:
        """Create a job and seed all pipeline steps as pending."""
        job = Job(
            video_id=video_id,
            pipeline_name=pipeline_name,
            status="pending",
        )
        job = self.repo.add(job)

        for name in PIPELINE_STEPS:
            self.step_repo.add(JobStep(job_id=job.id, step_name=name, status="pending"))

        logger.info("Created job %d for video %d", job.id, video_id)
        return job

    def get(self, job_id: int) -> Job:
        """Get job by ID or raise."""
        job = self.repo.get(job_id)
        if job is None:
            raise NotFoundException(f"Job {job_id} tidak ditemukan")
        return job

    def start_step(self, job_id: int, step_name: str) -> JobStep:
        """Mark a step as running."""
        job = self.get(job_id)
        job.status = "running"
        job.current_step = step_name
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        self.db.commit()

        step = self._get_step(job_id, step_name)
        step.status = "running"
        step.started_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(step)
        return step

    def finish_step(self, job_id: int, step_name: str, success: bool = True, error: str | None = None) -> JobStep:
        """Mark a step finished (success or failed)."""
        step = self._get_step(job_id, step_name)
        now = datetime.now(UTC)
        step.finished_at = now
        step.status = "success" if success else "failed"
        step.error_message = error
        if step.started_at:
            step.duration_ms = int((now - step.started_at).total_seconds() * 1000)
        self.db.commit()
        self.db.refresh(step)

        if not success:
            job = self.get(job_id)
            job.status = "failed"
            job.error_message = error
            job.finished_at = now
            self.db.commit()

        return step

    def complete_job(self, job_id: int) -> Job:
        """Mark entire job as completed."""
        job = self.get(job_id)
        job.status = "completed"
        job.finished_at = datetime.now(UTC)
        job.current_step = None
        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel(self, job_id: int) -> Job:
        """Cancel a running job."""
        job = self.get(job_id)
        if job.status not in ("pending", "running"):
            return job
        job.status = "cancelled"
        job.error_message = "Dibatalkan oleh user"
        job.finished_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(job)
        logger.info("Job %d cancelled", job_id)
        return job

    def get_running_by_video(self) -> dict[int, dict]:
        """Map video_id -> {job_id, current_step} for running jobs."""
        result: dict[int, dict] = {}
        for job in self.repo.get_running():
            result[job.video_id] = {
                "job_id": job.id,
                "current_step": job.current_step or "running",
            }
        return result

    def mark_stale_failed(self) -> int:
        """Mark pending/running jobs as failed (orphaned after restart)."""
        stale = self.repo.get_stale()
        for job in stale:
            job.status = "failed"
            job.error_message = "Job terputus karena server restart."
            if job.started_at is None:
                job.started_at = job.created_at
            job.finished_at = job.started_at
        if stale:
            self.db.commit()
            logger.info("Marked %d stale job(s) as failed", len(stale))
        return len(stale)

    def _get_step(self, job_id: int, step_name: str) -> JobStep:
        """Find step by job + name."""
        steps = self.step_repo.get_by_job(job_id)
        for s in steps:
            if s.step_name == step_name:
                return s
        raise NotFoundException(f"Step '{step_name}' not found for job {job_id}")
