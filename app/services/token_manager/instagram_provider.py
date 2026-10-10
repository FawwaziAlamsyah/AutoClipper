"""Provider token Instagram API with Instagram Login."""

from datetime import datetime, timedelta, timezone
import hashlib
import logging

import httpx
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.security.token_crypto import encrypt_token
from app.models.oauth_token_model import OAuthTokenModel
from app.repositories.oauth_token_repository import OAuthTokenRepository
from app.services.token_manager.base import (
    RefreshResult,
    TokenInvalidError,
    TokenProvider,
    TokenTransientError,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class InstagramTokenProvider(TokenProvider):
    """Token provider untuk Instagram API (Reels via Instagram Login)."""

    platform: str = "instagram"

    def _build_url(self, path: str) -> str:
        """Bangun URL endpoint Instagram Graph API dengan opsional prefix versi."""
        base = settings.IG_GRAPH_BASE_URL.rstrip("/")
        version = settings.IG_GRAPH_VERSION.strip("/")
        p = path.lstrip("/")
        if version:
            return f"{base}/{version}/{p}"
        return f"{base}/{p}"

    def sync_from_config(self, db: Session) -> None:
        """Seed token dari .env ke DB atau perbarui jika token di .env berganti."""
        if not settings.IG_ACCESS_TOKEN or not settings.IG_USER_ID:
            logger.debug("Instagram config IG_ACCESS_TOKEN atau IG_USER_ID belum diisi di .env")
            return

        fingerprint = hashlib.sha256(settings.IG_ACCESS_TOKEN.encode()).hexdigest()
        repo = OAuthTokenRepository(db)
        record = repo.get(self.platform, settings.IG_USER_ID)

        now = datetime.now(timezone.utc)
        issued_at = now
        expiry_estimated = True

        if settings.IG_TOKEN_ISSUED_AT:
            try:
                parsed = datetime.fromisoformat(settings.IG_TOKEN_ISSUED_AT)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                issued_at = parsed
                expiry_estimated = False
            except Exception:
                logger.warning(
                    "Format IG_TOKEN_ISSUED_AT ('%s') tidak valid, memakai estimasi sekarang",
                    settings.IG_TOKEN_ISSUED_AT,
                )
                issued_at = now
                expiry_estimated = True

        expires_at = issued_at + timedelta(days=settings.IG_TOKEN_LIFETIME_DAYS)

        if record is None:
            logger.info("Menyimpan token Instagram baru dari .env (ID: %s)", settings.IG_USER_ID)
            new_record = OAuthTokenModel(
                platform=self.platform,
                account_id=settings.IG_USER_ID,
                access_token_encrypted=encrypt_token(settings.IG_ACCESS_TOKEN),
                issued_at=issued_at,
                expires_at=expires_at,
                expiry_estimated=expiry_estimated,
                status="active",
                seed_fingerprint=fingerprint,
            )
            repo.upsert(new_record)
        elif record.seed_fingerprint != fingerprint:
            logger.info(
                "Mendeteksi perubahan token Instagram di .env, memperbarui DB (ID: %s)",
                settings.IG_USER_ID,
            )
            record.access_token_encrypted = encrypt_token(settings.IG_ACCESS_TOKEN)
            record.issued_at = issued_at
            record.expires_at = expires_at
            record.expiry_estimated = expiry_estimated
            record.seed_fingerprint = fingerprint
            record.status = "active"
            record.last_error = None
            repo.save(record)
        else:
            logger.debug("Token Instagram di DB cocok dengan fingerprint .env, tidak ada perubahan seed")

    def validate(self, record: OAuthTokenModel, access_token: str) -> ValidationResult:
        """Validasi token aktif dan pastikan akun bertipe Professional (Business/Creator)."""
        is_fb_graph = "graph.facebook.com" in settings.IG_GRAPH_BASE_URL
        if is_fb_graph:
            url = self._build_url(record.account_id)
            params = {"fields": "id,username,name", "access_token": access_token}
        else:
            url = self._build_url("me")
            params = {"fields": "user_id,username,account_type", "access_token": access_token}

        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=15.0)
        except httpx.TimeoutException as e:
            raise TokenTransientError(f"Timeout saat menghubungi Instagram Graph API: {e}") from e
        except httpx.RequestError as e:
            raise TokenTransientError(f"Koneksi gagal ke Instagram Graph API: {e}") from e

        try:
            data = resp.json()
        except Exception:
            data = {}

        if "error" in data:
            err = data["error"]
            code = err.get("code")
            msg = err.get("message", "Unknown error")
            if code == 190 or resp.status_code == 401:
                raise TokenInvalidError(
                    f"Token Instagram tidak valid atau telah kedaluwarsa (code 190): {msg}"
                )
            raise TokenTransientError(f"Instagram Graph API error (code {code}): {msg}")

        if resp.status_code == 401:
            raise TokenInvalidError(f"Token Instagram tidak valid (HTTP 401): {resp.text}")

        if resp.status_code >= 500:
            raise TokenTransientError(f"Instagram Graph API server error: HTTP {resp.status_code}")

        if resp.status_code == 429:
            raise TokenTransientError("Instagram Graph API rate limit tercapai (HTTP 429)")

        if resp.status_code == 200:
            user_id = str(data.get("user_id") or data.get("id") or "")
            if user_id != str(record.account_id):
                raise TokenInvalidError(
                    f"Token milik akun ID '{user_id}', tidak cocok dengan IG_USER_ID '{record.account_id}'"
                )
            if "account_type" in data:
                account_type = str(data.get("account_type", "")).upper()
                if account_type not in ("BUSINESS", "MEDIA_CREATOR"):
                    raise TokenInvalidError(
                        f"Akun harus Professional (Business/Creator), tipe akun saat ini: '{account_type or 'PERSONAL'}'"
                    )
            username = data.get("username", "") or data.get("name", "")
            return ValidationResult(ok=True, account_label=username)

        raise TokenTransientError(f"Validasi token Instagram gagal dengan HTTP {resp.status_code}")

    def needs_refresh(self, record: OAuthTokenModel, now: datetime) -> bool:
        """Cek apakah token Instagram sudah memenuhi syarat untuk di-refresh.

        Syarat refresh:
        - status == 'active'
        - DAN sisa masa berlaku < IG_TOKEN_REFRESH_BEFORE_DAYS (default 5 hari)
        - DAN umur token >= IG_TOKEN_MIN_AGE_HOURS (default 24 jam)
        - Pengecualian: expiry_estimated=True boleh refresh satu kali sampai berhasil.
        """
        if record.status != "active":
            return False

        # Jika tanggal terbit token diestimasi, boleh dicoba refresh sekali
        if record.expiry_estimated:
            return True

        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        days_left = (expires_at - now).total_seconds() / 86400.0

        if days_left >= settings.IG_TOKEN_REFRESH_BEFORE_DAYS:
            return False

        ref_time = record.last_refreshed_at or record.issued_at
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        age_hours = (now - ref_time).total_seconds() / 3600.0

        return age_hours >= settings.IG_TOKEN_MIN_AGE_HOURS

    def refresh(
        self, record: OAuthTokenModel, access_token: str, refresh_token: str | None
    ) -> RefreshResult:
        """Refresh long-lived access token ke Instagram Graph API."""
        if access_token.startswith("EAA") and not access_token.startswith("dummy"):
            logger.info("Token Facebook Graph API (EAA...) tidak memakai ig_refresh_token, memperbarui estimasi lokal")
            now = datetime.now(timezone.utc)
            return RefreshResult(
                access_token=access_token,
                expires_at=now + timedelta(days=settings.IG_TOKEN_LIFETIME_DAYS),
            )

        url = self._build_url("refresh_access_token")
        params = {
            "grant_type": "ig_refresh_token",
            "access_token": access_token,
        }

        try:
            resp = httpx.get(url, params=params, timeout=15.0)
        except httpx.TimeoutException as e:
            raise TokenTransientError(f"Timeout saat refresh token Instagram: {e}") from e
        except httpx.RequestError as e:
            raise TokenTransientError(f"Koneksi gagal saat refresh token Instagram: {e}") from e

        try:
            data = resp.json()
        except Exception:
            data = {}

        if "error" in data:
            err = data["error"]
            code = err.get("code")
            msg = err.get("message", "Unknown error")
            if code == 190 or resp.status_code == 401:
                raise TokenInvalidError(
                    f"Gagal me-refresh token Instagram (code 190 / expired): {msg}"
                )
            raise TokenTransientError(f"Instagram Graph API error saat refresh (code {code}): {msg}")

        if resp.status_code == 200:
            new_token = data.get("access_token")
            if not new_token:
                raise TokenTransientError("Response refresh token Instagram tidak memuat access_token")
            expires_in = int(data.get("expires_in", settings.IG_TOKEN_LIFETIME_DAYS * 86400))
            now = datetime.now(timezone.utc)
            new_expires_at = now + timedelta(seconds=expires_in)
            return RefreshResult(access_token=new_token, expires_at=new_expires_at)

        if resp.status_code == 401:
            raise TokenInvalidError(f"Refresh token Instagram gagal (HTTP 401): {resp.text}")

        raise TokenTransientError(f"Refresh token Instagram gagal dengan HTTP {resp.status_code}")
