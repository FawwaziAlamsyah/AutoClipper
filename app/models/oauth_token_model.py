"""SQLAlchemy model untuk penyimpanan token OAuth generik (Instagram, TikTok, YouTube, dll)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OAuthTokenModel(Base, TimestampMixin):
    """Penyimpanan terpusat token OAuth berbagai platform."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("platform", "account_id", name="uq_oauth_tokens_platform_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiry_estimated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
