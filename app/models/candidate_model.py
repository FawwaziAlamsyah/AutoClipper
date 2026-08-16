"""SQLAlchemy model for the candidates table."""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class CandidateModel(Base, TimestampMixin):
    """Hasil Score Engine + Candidate Generator — kandidat klip sebelum di-render."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    hook_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="candidate")
    actual_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_training_example: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    video: Mapped["VideoModel"] = relationship(back_populates="candidates")
    job: Mapped["JobModel"] = relationship(back_populates="candidates")
    category: Mapped["CategoryModel | None"] = relationship(back_populates="candidates")
    clips: Mapped[list["ClipModel"]] = relationship(back_populates="candidate")
