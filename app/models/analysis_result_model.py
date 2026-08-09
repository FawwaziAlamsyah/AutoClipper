"""SQLAlchemy model for the analysis_results table."""

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AnalysisResultModel(Base, TimestampMixin):
    """Output semua analyzer: voice, face, gesture, scene, keyword, hook, LLM, dst."""

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id"), nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), nullable=False)
    analyzer_type: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[float | None] = mapped_column(Float)
    end_time: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    result_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    video: Mapped["VideoModel"] = relationship(back_populates="analysis_results")
    job: Mapped["JobModel"] = relationship(back_populates="analysis_results")
