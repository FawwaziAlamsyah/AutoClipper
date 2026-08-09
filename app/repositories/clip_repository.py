"""Repository for Clip model."""

from app.models.clip_model import Clip
from app.repositories.base_repository import PostgresRepository


class ClipRepository(PostgresRepository[Clip]):
    """PostgreSQL repository for clips."""

    model_class = Clip

    def get_by_video(self, video_id: int) -> list[Clip]:
        """Get all clips for a video."""
        return list(self.db.query(Clip).filter(Clip.video_id == video_id).all())

    def get_by_candidate(self, candidate_id: int) -> list[Clip]:
        """Get all clips generated from a candidate."""
        return list(
            self.db.query(Clip).filter(Clip.candidate_id == candidate_id).all()
        )
