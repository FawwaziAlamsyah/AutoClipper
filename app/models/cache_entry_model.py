"""SQLAlchemy model for the cache_entries table."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class CacheEntry(Base, TimestampMixin):
    """Metadata cache hasil antara (file besar tetap di data/cache/)."""

    __tablename__ = "cache_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    video_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("videos.id"))
    step_name: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    video: Mapped["Video | None"] = relationship(back_populates="cache_entries")
