"""Repository for Video model."""

from sqlalchemy import exists, or_

from app.models.job_model import JobModel
from app.models.video_model import VideoModel
from app.repositories.base_repository import PostgresRepository


class VideoRepository(PostgresRepository[VideoModel]):
    """PostgreSQL repository for videos."""

    model_class = VideoModel

    def update_status(self, video_id: int, status: str) -> VideoModel | None:
        """Update a video's status."""
        video = self.get(video_id)
        if video is None:
            return None
        video.status = status
        self.db.commit()
        self.db.refresh(video)
        return video

    def list_for_upload(self) -> list[VideoModel]:
        """List videos for Upload UI, excluding training-only source videos."""
        has_job = exists().where(JobModel.video_id == VideoModel.id)
        has_normal_job = exists().where(
            JobModel.video_id == VideoModel.id,
            JobModel.job_type != "training_ingest",
        )
        return list(
            self.db.query(VideoModel)
            .filter(or_(~has_job, has_normal_job))
            .order_by(VideoModel.id.desc())
            .all()
        )

    def get_ready_not_archived(self) -> list[VideoModel]:
        """Return videos with status='ready' that have not been archived yet."""
        return list(
            self.db.query(VideoModel)
            .filter(
                VideoModel.status == "ready",
                VideoModel.is_archived == False,  # noqa: E712
            )
            .all()
        )
