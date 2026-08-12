"""Job & job step lifecycle management."""

import logging
from datetime import datetime, UTC

from sqlalchemy.orm import Session

from app.core.exceptions.base import NotFoundException
from app.models.job_model import JobModel
from app.models.job_step_model import JobStepModel
from app.repositories.job_repository import JobRepository, JobStepRepository

logger = logging.getLogger(__name__)

# Step pipeline utama — hanya ini yang di-seed pending saat job dibuat.
# Step opsional (generate/subtitle/export) dibuat via ensure_step saat dijalankan.
PIPELINE_STEPS = ("extract", "transcribe", "analyze", "score", "complete")

# Sub-step analyzer yang di-seed saat tahap analyze dimulai.
# Nama step = analyzer_type di registry (harus match agar start_step/finish_step
# menemukan row job_steps yang benar).
ANALYZER_STEPS = (
    "llm_content",
    "face_emotion",
    "voice_emotion",
    "gesture",
    "eye_contact",
    "scene",
    "audio",
)


class JobService:
    """Create and track pipeline jobs."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db
        self.repo = JobRepository(db)
        self.step_repo = JobStepRepository(db)

    def create(self, video_id: int, pipeline_name: str = "auto_clipper_v1", job_type: str = "discovery") -> JobModel:
        """Create a job and seed all pipeline steps as pending."""
        job = JobModel(
            video_id=video_id,
            pipeline_name=pipeline_name,
            status="pending",
            job_type=job_type,
        )
        job = self.repo.add(job)

        for name in PIPELINE_STEPS:
            self.step_repo.add(JobStepModel(job_id=job.id, step_name=name, status="pending"))

        logger.info("Created job %d for video %d", job.id, video_id)
        return job

    def seed_analyzer_steps(self, job_id: int) -> None:
        """Seed sub-step analyzer sebagai pending saat tahap analyze dimulai."""
        existing = {s.step_name for s in self.step_repo.get_by_job(job_id)}
        for name in ANALYZER_STEPS:
            if name not in existing:
                self.step_repo.add(JobStepModel(job_id=job_id, step_name=name, status="pending"))

    def ensure_step(self, job_id: int, step_name: str) -> JobStepModel:
        """Buat step kalau belum ada (untuk step opsional generate/subtitle)."""
        for s in self.step_repo.get_by_job(job_id):
            if s.step_name == step_name:
                return s
        return self.step_repo.add(JobStepModel(job_id=job_id, step_name=step_name, status="pending"))

    def start_optional_step(self, job_id: int, step_name: str) -> JobStepModel:
        """Catat start step opsional (generate/subtitle) TANPA mengubah status job.

        Job yang sudah completed tidak boleh jadi running lagi karena generate clip
        — step ini murni pencatatan job_steps, bukan pipeline utama.
        """
        step = self.ensure_step(job_id, step_name)
        step.status = "running"
        step.started_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(step)
        return step

    def finish_optional_step(self, job_id: int, step_name: str, success: bool = True, error: str | None = None) -> JobStepModel:
        """Catat finish step opsional tanpa menyentuh status job."""
        step = self._get_step(job_id, step_name)
        now = datetime.now(UTC)
        step.finished_at = now
        step.status = "success" if success else "failed"
        step.error_message = error
        if step.started_at:
            step.duration_ms = int((now - step.started_at).total_seconds() * 1000)
        self.db.commit()
        self.db.refresh(step)
        return step

    def get(self, job_id: int) -> JobModel:
        """Get job by ID or raise."""
        job = self.repo.get(job_id)
        if job is None:
            raise NotFoundException(f"Job {job_id} tidak ditemukan")
        return job

    def start_step(self, job_id: int, step_name: str) -> JobStepModel:
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

    def finish_step(self, job_id: int, step_name: str, success: bool = True, error: str | None = None) -> JobStepModel:
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

    def complete_job(self, job_id: int) -> JobModel:
        """Mark entire job as completed."""
        job = self.get(job_id)
        job.status = "completed"
        job.finished_at = datetime.now(UTC)
        job.current_step = None
        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel(self, job_id: int) -> JobModel:
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
        """Map video_id -> {job_id, current_step} for active (pending/running) jobs."""
        result: dict[int, dict] = {}
        for job in self.repo.get_running():
            result[job.video_id] = {
                "job_id": job.id,
                "current_step": job.current_step or "running",
            }
        return result

    def get_active_list(self) -> list[dict]:
        """Return list of active jobs with video info (for global indicator)."""
        return [
            {
                "job_id": job.id,
                "video_id": job.video_id,
                "status": job.status,
                "current_step": job.current_step or "running",
            }
            for job in self.repo.get_running()
        ]

    def get_status(self, job_id: int) -> dict:
        """Return job status with per-step progress (for polling)."""
        job = self.get(job_id)
        steps = self.step_repo.get_by_job(job_id)
        completed = sum(1 for s in steps if s.status == "success")
        total = len(steps)
        progress_percent = round((completed / total) * 100) if total else 0

        return {
            "job_id": job.id,
            "status": job.status,
            "current_step": job.current_step,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "error_message": job.error_message,
            "progress_percent": progress_percent,
            "total_steps": total,
            "completed_steps": completed,
            "steps": [
                {
                    "step_name": s.step_name,
                    "status": s.status,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                    "duration_ms": s.duration_ms,
                    "error_message": s.error_message,
                }
                for s in steps
            ],
        }

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

    def _get_step(self, job_id: int, step_name: str) -> JobStepModel:
        """Find step by job + name."""
        steps = self.step_repo.get_by_job(job_id)
        for s in steps:
            if s.step_name == step_name:
                return s
        raise NotFoundException(f"Step '{step_name}' not found for job {job_id}")
