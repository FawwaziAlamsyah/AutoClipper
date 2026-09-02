"""SQLAlchemy model for the videos table."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class VideoModel(Base, TimestampMixin):
    """Video sumber (hasil upload atau download)."""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="uploaded")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    jobs: Mapped[list["JobModel"]] = relationship(back_populates="video")
    transcripts: Mapped[list["TranscriptModel"]] = relationship(back_populates="video")
    speakers: Mapped[list["SpeakerModel"]] = relationship(back_populates="video")
    analysis_results: Mapped[list["AnalysisResultModel"]] = relationship(back_populates="video")
    candidates: Mapped[list["CandidateModel"]] = relationship(back_populates="video")
    clips: Mapped[list["ClipModel"]] = relationship(back_populates="video")
    history_entries: Mapped[list["HistoryModel"]] = relationship(back_populates="video")
    cache_entries: Mapped[list["CacheEntryModel"]] = relationship(back_populates="video")
