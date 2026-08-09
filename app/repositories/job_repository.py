"""Repository for Job and JobStep models."""

from sqlalchemy.orm import Session

from app.models.job_model import JobModel
from app.models.job_step_model import JobStepModel
from app.repositories.base_repository import PostgresRepository


class JobRepository(PostgresRepository[JobModel]):
    """PostgreSQL repository for jobs."""

    model_class = JobModel

    def get_by_video(self, video_id: int) -> list[JobModel]:
        """Retrieve all jobs for a video."""
        return list(self.db.query(JobModel).filter(JobModel.video_id == video_id).all())

    def get_running(self) -> list[JobModel]:
        """Retrieve active (pending or running) jobs."""
        return list(
            self.db.query(JobModel).filter(JobModel.status.in_(["pending", "running"])).all()
        )

    def get_stale(self) -> list[JobModel]:
        """Retrieve jobs stuck in pending/running (orphaned after restart)."""
        return list(
            self.db.query(JobModel).filter(JobModel.status.in_(["pending", "running"])).all()
        )

    def get_latest_by_video(self, video_id: int) -> JobModel | None:
        """Get the most recent job for a video."""
        return (
            self.db.query(JobModel)
            .filter(JobModel.video_id == video_id)
            .order_by(JobModel.created_at.desc())
            .first()
        )


class JobStepRepository(PostgresRepository[JobStepModel]):
    """PostgreSQL repository for job steps."""

    model_class = JobStepModel

    def get_by_job(self, job_id: int) -> list[JobStepModel]:
        """Retrieve all steps for a job."""
        return list(self.db.query(JobStepModel).filter(JobStepModel.job_id == job_id).all())
