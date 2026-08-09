"""Repository for History model."""

from app.models.history_model import History
from app.repositories.base_repository import PostgresRepository


class HistoryRepository(PostgresRepository[History]):
    """PostgreSQL repository for history entries."""

    model_class = History

    def get_by_video(self, video_id: int) -> list[History]:
        """Get all history entries for a video."""
        return list(
            self.db.query(History)
            .filter(History.video_id == video_id)
            .order_by(History.created_at.desc())
            .all()
        )

    def get_recent(self, limit: int = 50) -> list[History]:
        """Get the most recent history entries."""
        return list(
            self.db.query(History)
            .order_by(History.created_at.desc())
            .limit(limit)
            .all()
        )
