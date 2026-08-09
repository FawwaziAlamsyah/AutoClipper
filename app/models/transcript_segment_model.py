"""SQLAlchemy model for the transcript_segments table."""

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TranscriptSegmentModel(Base):
    """Potongan transcript per-kalimat/per-waktu."""

    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[int] = mapped_column(Integer, ForeignKey("transcripts.id"), nullable=False)
    speaker_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("speakers.id"))
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)

    transcript: Mapped["TranscriptModel"] = relationship(back_populates="segments")
    speaker: Mapped["SpeakerModel | None"] = relationship(back_populates="segments")
