"""SQLAlchemy model for the subtitles table."""

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SubtitleModel(Base, TimestampMixin):
    """Subtitle per clip (bisa multi-bahasa/multi-format)."""

    __tablename__ = "subtitles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(Integer, ForeignKey("clips.id"), nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)

    clip: Mapped["ClipModel"] = relationship(back_populates="subtitles")
