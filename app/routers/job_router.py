"""Job status endpoints (for async progress polling)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions.base import NotFoundException
from app.db.session import get_db
from app.models.job_model import Job
from app.repositories.job_repository import JobRepository, JobStepRepository
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _repos(db: Session) -> tuple[JobRepository, JobStepRepository]:
    return JobRepository(db), JobStepRepository(db)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    """Cancel a running job."""
    service = JobService(db)
    job = service.cancel(job_id)
    return {"job_id": job.id, "status": job.status}


@router.get("/{job_id}")
def get_job_status(job_id: int, db: Session = Depends(get_db)) -> dict:
    """Return job status with per-step progress."""
    job_repo, step_repo = _repos(db)
    job = job_repo.get(job_id)
    if job is None:
        raise NotFoundException(f"Job {job_id} tidak ditemukan")

    steps = step_repo.get_by_job(job_id)
    return {
        "job_id": job.id,
        "status": job.status,
        "current_step": job.current_step,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error_message": job.error_message,
        "steps": [
            {
                "step_name": s.step_name,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "error_message": s.error_message,
            }
            for s in steps
        ],
    }
