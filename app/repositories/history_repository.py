"""Repository for History model."""

from app.models.history_model import HistoryModel
from app.repositories.base_repository import PostgresRepository


class HistoryRepository(PostgresRepository[HistoryModel]):
    """PostgreSQL repository for history entries."""

    model_class = HistoryModel

    def get_by_video(self, video_id: int) -> list[HistoryModel]:
        """Get all history entries for a video."""
        return list(
            self.db.query(HistoryModel)
            .filter(HistoryModel.video_id == video_id)
            .order_by(HistoryModel.created_at.desc())
            .all()
        )

    def get_recent(self, limit: int = 50) -> list[HistoryModel]:
        """Get the most recent history entries."""
        return list(
            self.db.query(HistoryModel)
            .order_by(HistoryModel.created_at.desc())
            .limit(limit)
            .all()
        )
