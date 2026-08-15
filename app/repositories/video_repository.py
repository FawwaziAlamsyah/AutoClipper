"""Repository for Video model."""

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
