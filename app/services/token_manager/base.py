"""Base classes, dataclasses, and exceptions for TokenManager providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.oauth_token_model import OAuthTokenModel


@dataclass(frozen=True)
class RefreshResult:
    """Hasil operasi token refresh."""

    access_token: str
    expires_at: datetime  # timezone-aware UTC
    refresh_token: str | None = None  # None = jangan ganti refresh token lama


@dataclass(frozen=True)
class ValidationResult:
    """Hasil validasi keaktifan token ke API platform."""

    ok: bool
    account_label: str | None = None  # mis. username / display name
    detail: str | None = None


class TokenInvalidError(Exception):
    """Token sudah tidak valid / kedaluwarsa / izin dicabut (status -> needs_reconnect)."""


class TokenTransientError(Exception):
    """Error sementara (jaringan, 5xx server platform, rate limit, belum saatnya refresh).

    Status akun tidak diubah; coba lagi nanti.
    """


class TokenProvider(ABC):
    """Antarmuka dasar untuk provider token tiap platform."""

    platform: str

    def sync_from_config(self, db: Session) -> None:
        """Default no-op; dioverride provider bila perlu seed dari .env/settings."""
        pass

    @abstractmethod
    def needs_refresh(self, record: OAuthTokenModel, now: datetime) -> bool:
        """Cek apakah token sudah memenuhi kriteria untuk di-refresh."""
        ...

    @abstractmethod
    def refresh(
        self, record: OAuthTokenModel, access_token: str, refresh_token: str | None
    ) -> RefreshResult:
        """Refresh token ke endpoint provider menggunakan access/refresh token yang sudah didekripsi."""
        ...

    @abstractmethod
    def validate(self, record: OAuthTokenModel, access_token: str) -> ValidationResult:
        """Validasi token ke endpoint platform menggunakan token yang sudah didekripsi."""
        ...
