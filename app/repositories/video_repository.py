"""Repository for Video model."""

from sqlalchemy.orm import Session

from app.models.video_model import VideoModel
from app.repositories.base_repository import PostgresRepository


class VideoRepository(PostgresRepository[VideoModel]):
    """PostgreSQL repository for videos."""

    model_class = VideoModel

    def get_by_status(self, status: str) -> list[VideoModel]:
        """Retrieve all videos with a given status."""
        return list(self.db.query(VideoModel).filter(VideoModel.status == status).all())

    def update_status(self, video_id: int, status: str) -> VideoModel | None:
        """Update a video's status."""
        video = self.get(video_id)
        if video is None:
            return None
        video.status = status
        self.db.commit()
        self.db.refresh(video)
        return video
