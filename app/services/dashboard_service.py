"""Dashboard service: aggregate stats and recent activity for the dashboard page."""

import logging

from sqlalchemy.orm import Session

from app.models.video_model import Video
from app.models.job_model import Job
from app.models.clip_model import Clip
from app.models.history_model import History

logger = logging.getLogger(__name__)


class DashboardService:
    """Compute dashboard statistics and recent history."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db

    def get_stats(self) -> dict:
        """Return aggregate counters for the dashboard."""
        return {
            "total_videos": self.db.query(Video).count(),
            "completed_jobs": self.db.query(Job).filter(Job.status == "completed").count(),
            "total_clips": self.db.query(Clip).count(),
            "pending_jobs": self.db.query(Job).filter(Job.status.in_(["pending", "running"])).count(),
        }

    def get_recent_history(self, limit: int = 5) -> list[History]:
        """Return the most recent history entries."""
        return list(
            self.db.query(History)
            .order_by(History.created_at.desc())
            .limit(limit)
            .all()
        )