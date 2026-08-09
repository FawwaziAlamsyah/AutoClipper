"""SQLAlchemy model for the history table."""

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class History(Base, TimestampMixin):
    """Audit trail lintas video/job."""

    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("videos.id"))
    job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("jobs.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    video: Mapped["Video | None"] = relationship(back_populates="history_entries")
    job: Mapped["Job | None"] = relationship(back_populates="history_entries")
