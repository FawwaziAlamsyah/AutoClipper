"""Repository for Job and JobStep models."""

from sqlalchemy.orm import Session

from app.models.job_model import Job
from app.models.job_step_model import JobStep
from app.repositories.base_repository import PostgresRepository


class JobRepository(PostgresRepository[Job]):
    """PostgreSQL repository for jobs."""

    model_class = Job

    def get_by_video(self, video_id: int) -> list[Job]:
        """Retrieve all jobs for a video."""
        return list(self.db.query(Job).filter(Job.video_id == video_id).all())

    def get_running(self) -> list[Job]:
        """Retrieve all running jobs."""
        return list(self.db.query(Job).filter(Job.status == "running").all())

    def get_stale(self) -> list[Job]:
        """Retrieve jobs stuck in pending/running (orphaned after restart)."""
        return list(
            self.db.query(Job).filter(Job.status.in_(["pending", "running"])).all()
        )

    def get_latest_by_video(self, video_id: int) -> Job | None:
        """Get the most recent job for a video."""
        return (
            self.db.query(Job)
            .filter(Job.video_id == video_id)
            .order_by(Job.created_at.desc())
            .first()
        )


class JobStepRepository(PostgresRepository[JobStep]):
    """PostgreSQL repository for job steps."""

    model_class = JobStep

    def get_by_job(self, job_id: int) -> list[JobStep]:
        """Retrieve all steps for a job."""
        return list(self.db.query(JobStep).filter(JobStep.job_id == job_id).all())
