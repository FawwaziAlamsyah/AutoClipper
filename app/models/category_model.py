"""SQLAlchemy model for the categories table."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CategoryModel(Base):
    """Kategori clip style yang bisa dibuat user (Gaming Funny, Podcast Sedih, dst)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # Fase depan: strategi hook foreground untuk kategori ini — belum aktif, hanya disiapkan.
    preferred_hook_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    candidates: Mapped[list["CandidateModel"]] = relationship(back_populates="category")
    jobs: Mapped[list["JobModel"]] = relationship(back_populates="category")
