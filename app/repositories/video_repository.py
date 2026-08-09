"""Repository for Video model."""

from sqlalchemy.orm import Session

from app.models.video_model import Video
from app.repositories.base_repository import PostgresRepository


class VideoRepository(PostgresRepository[Video]):
    """PostgreSQL repository for videos."""

    model_class = Video

    def get_by_status(self, status: str) -> list[Video]:
        """Retrieve all videos with a given status."""
        return list(self.db.query(Video).filter(Video.status == status).all())

    def update_status(self, video_id: int, status: str) -> Video | None:
        """Update a video's status."""
        video = self.get(video_id)
        if video is None:
            return None
        video.status = status
        self.db.commit()
        self.db.refresh(video)
        return video
