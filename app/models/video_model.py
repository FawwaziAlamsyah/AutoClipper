"""SQLAlchemy model for the videos table."""

from sqlalchemy import Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Video(Base, TimestampMixin):
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
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="uploaded")

    jobs: Mapped[list["Job"]] = relationship(back_populates="video")
    transcripts: Mapped[list["Transcript"]] = relationship(back_populates="video")
    speakers: Mapped[list["Speaker"]] = relationship(back_populates="video")
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(back_populates="video")
    candidates: Mapped[list["Candidate"]] = relationship(back_populates="video")
    clips: Mapped[list["Clip"]] = relationship(back_populates="video")
    history_entries: Mapped[list["History"]] = relationship(back_populates="video")
    cache_entries: Mapped[list["CacheEntry"]] = relationship(back_populates="video")
