"""SQLAlchemy model for the jobs table."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class JobModel(Base, TimestampMixin):
    """Satu kali eksekusi pipeline untuk satu video."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    pipeline_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    job_type: Mapped[str] = mapped_column(Text, nullable=False, default="discovery")
    current_step: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    # Progress terakhir yang sudah "dikunci" (monotonic) — dijaga supaya stale
    # update tidak bisa nurunin progress yang sudah dikirim ke UI.
    progress_percent: Mapped[int | None] = mapped_column(Integer)

    video: Mapped["VideoModel"] = relationship(back_populates="jobs")
    category: Mapped["CategoryModel | None"] = relationship(back_populates="jobs")
    steps: Mapped[list["JobStepModel"]] = relationship(back_populates="job")
    transcripts: Mapped[list["TranscriptModel"]] = relationship(back_populates="job")
    analysis_results: Mapped[list["AnalysisResultModel"]] = relationship(back_populates="job")
    candidates: Mapped[list["CandidateModel"]] = relationship(back_populates="job")
    history_entries: Mapped[list["HistoryModel"]] = relationship(back_populates="job")
