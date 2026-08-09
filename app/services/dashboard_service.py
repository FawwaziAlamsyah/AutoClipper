"""Dashboard service: aggregate stats and recent activity for the dashboard page."""

import logging

from sqlalchemy.orm import Session

from app.models.video_model import VideoModel
from app.models.job_model import JobModel
from app.models.clip_model import ClipModel
from app.models.history_model import HistoryModel

logger = logging.getLogger(__name__)


class DashboardService:
    """Compute dashboard statistics and recent history."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db

    def get_stats(self) -> dict:
        """Return aggregate counters for the dashboard."""
        return {
            "total_videos": self.db.query(VideoModel).count(),
            "completed_jobs": self.db.query(JobModel).filter(JobModel.status == "completed").count(),
            "total_clips": self.db.query(ClipModel).count(),
            "pending_jobs": self.db.query(JobModel).filter(JobModel.status.in_(["pending", "running"])).count(),
        }

    def get_recent_history(self, limit: int = 5) -> list[HistoryModel]:
        """Return the most recent history entries."""
        return list(
            self.db.query(HistoryModel)
            .order_by(HistoryModel.created_at.desc())
            .limit(limit)
            .all()
        )