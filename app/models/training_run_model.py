"""SQLAlchemy model for the training_runs table."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TrainingRunModel(Base, TimestampMixin):
    """Satu kali eksekusi training model — riwayat lengkap, tidak ketimpa."""

    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    real_performance_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_liked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    val_mae: Mapped[float] = mapped_column(Float, nullable=False)
    val_r2: Mapped[float] = mapped_column(Float, nullable=False)
    feature_importance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
