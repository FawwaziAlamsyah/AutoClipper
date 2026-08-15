"""Repository for Clip model."""

from app.models.clip_model import ClipModel
from app.repositories.base_repository import PostgresRepository


class ClipRepository(PostgresRepository[ClipModel]):
    """PostgreSQL repository for clips."""

    model_class = ClipModel

    def get_by_video(self, video_id: int) -> list[ClipModel]:
        """Get all clips for a video."""
        return list(self.db.query(ClipModel).filter(ClipModel.video_id == video_id).all())
