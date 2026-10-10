"""SQLAlchemy model for the instagram_posts table."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class InstagramPostModel(Base, TimestampMixin):
    """Riwayat dan status publikasi Reels klip ke Instagram."""

    __tablename__ = "instagram_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(Integer, ForeignKey("clips.id"), nullable=False, index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    share_to_feed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )  # queued | uploading | processing | published | failed | unknown
    container_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    clip: Mapped["ClipModel"] = relationship(back_populates="instagram_posts")  # noqa: F821
