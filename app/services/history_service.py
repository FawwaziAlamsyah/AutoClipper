"""History service."""

import logging

from sqlalchemy.orm import Session

from app.models.history_model import History
from app.repositories.history_repository import HistoryRepository

logger = logging.getLogger(__name__)


class HistoryService:
    """Manages audit trail / history entries."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.repo = HistoryRepository(db)
        self.db = db

    def log(
        self,
        action: str,
        description: str | None = None,
        video_id: int | None = None,
        job_id: int | None = None,
    ) -> History:
        """Record a history entry."""
        entry = History(
            video_id=video_id,
            job_id=job_id,
            action=action,
            description=description,
        )
        return self.repo.add(entry)

    def list_all(self, limit: int = 50) -> list[History]:
        """Return recent history entries."""
        return self.repo.get_recent(limit)

    def get_by_video(self, video_id: int) -> list[History]:
        """Return history for a specific video."""
        return self.repo.get_by_video(video_id)
