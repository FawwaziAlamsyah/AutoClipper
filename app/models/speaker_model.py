"""SQLAlchemy model for the speakers table."""

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SpeakerModel(Base, TimestampMixin):
    """Hasil Speaker Detection, per video."""

    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)

    video: Mapped["VideoModel"] = relationship(back_populates="speakers")
    segments: Mapped[list["TranscriptSegmentModel"]] = relationship(back_populates="speaker")
