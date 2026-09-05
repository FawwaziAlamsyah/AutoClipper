"""SQLAlchemy model for the clips table."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ClipModel(Base, TimestampMixin):
    """Hasil akhir Render/Export Engine — file klip jadi."""

    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("candidates.id"))
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(Text, nullable=False, default="16:9")
    has_subtitle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_watermark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tiktok_uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="rendering")
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_file_path: Mapped[str | None] = mapped_column(String(1024))
    hook_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    hook_skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # llm_unavailable|low_confidence|window_too_short|moment_too_close_to_start|render_failed

    candidate: Mapped["CandidateModel | None"] = relationship(back_populates="clips")
    video: Mapped["VideoModel"] = relationship(back_populates="clips")
    subtitles: Mapped[list["SubtitleModel"]] = relationship(back_populates="clip")
