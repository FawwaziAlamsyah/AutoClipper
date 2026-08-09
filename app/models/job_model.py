"""SQLAlchemy model for the jobs table."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Job(Base, TimestampMixin):
    """Satu kali eksekusi pipeline untuk satu video."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    pipeline_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    current_step: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    video: Mapped["Video"] = relationship(back_populates="jobs")
    steps: Mapped[list["JobStep"]] = relationship(back_populates="job")
    transcripts: Mapped[list["Transcript"]] = relationship(back_populates="job")
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(back_populates="job")
    candidates: Mapped[list["Candidate"]] = relationship(back_populates="job")
    history_entries: Mapped[list["History"]] = relationship(back_populates="job")
