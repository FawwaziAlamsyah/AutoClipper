"""SQLAlchemy model for the transcripts table."""

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class TranscriptModel(Base, TimestampMixin):
    """Hasil Speech-to-Text per video/job."""

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), nullable=False)
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)

    video: Mapped["VideoModel"] = relationship(back_populates="transcripts")
    job: Mapped["JobModel"] = relationship(back_populates="transcripts")
    segments: Mapped[list["TranscriptSegmentModel"]] = relationship(back_populates="transcript")
