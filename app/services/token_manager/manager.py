"""TokenManager — Pengelolaan token OAuth generik (storage, validation, refresh, locking)."""

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import threading

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.core.security.token_crypto import decrypt_token, encrypt_token
from app.models.oauth_token_model import OAuthTokenModel
from app.repositories.oauth_token_repository import OAuthTokenRepository
from app.services.token_manager.base import (
    TokenInvalidError,
    TokenProvider,
    TokenTransientError,
)

logger = logging.getLogger(__name__)


class TokenManager:
    """Manager terpusat untuk menyimpan, memvalidasi, dan me-refresh token OAuth berbagai platform."""

    def __init__(self) -> None:
        self._providers: dict[str, TokenProvider] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._master_lock = threading.Lock()

    def register(self, provider: TokenProvider) -> None:
        """Daftarkan provider baru ke registry."""
        self._providers[provider.platform] = provider
        logger.debug("TokenProvider '%s' terdaftar di TokenManager", provider.platform)

    def get_provider(self, platform: str) -> TokenProvider | None:
        """Ambil provider terdaftar untuk platform tertentu."""
        return self._providers.get(platform)

    def _get_lock(self, platform: str) -> threading.Lock:
        """Ambil atau buat lock per-platform agar proses refresh tidak balapan."""
        with self._master_lock:
            if platform not in self._locks:
                self._locks[platform] = threading.Lock()
            return self._locks[platform]

    def check_provider(self, db: Session, platform: str) -> OAuthTokenModel | None:
        """Alur sinkronisasi, validasi, dan refresh token untuk satu platform."""
        provider = self._providers.get(platform)
        if not provider:
            logger.warning("Token provider '%s' tidak terdaftar", platform)
            return None

        repo = OAuthTokenRepository(db)
        lock = self._get_lock(platform)
        with lock:
            # 1. Sync dari environment/config jika provider mendukungnya
            provider.sync_from_config(db)

            # 2. Ambil record dari DB
            record = repo.get(platform)
            if not record:
                logger.info("Token untuk platform '%s' belum dikonfigurasi", platform)
                return None

            now = datetime.now(timezone.utc)
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            days_left = max(0.0, (expires_at - now).total_seconds() / 86400.0)

            # 3. Cek apakah perlu refresh (tanpa panggilan validate rutin)
            if not provider.needs_refresh(record, now):
                logger.info(
                    "Token %s OK, sisa %.1f hari (skip, tanpa panggilan jaringan)",
                    platform,
                    days_left,
                )
                return record

            # 4. Refresh token dipicu
            if record.expiry_estimated:
                reason = "tanggal terbit belum pasti (expiry_estimated)"
            else:
                threshold = getattr(settings, f"{platform.upper()}_TOKEN_REFRESH_BEFORE_DAYS", settings.IG_TOKEN_REFRESH_BEFORE_DAYS)
                reason = f"sisa {days_left:.1f} hari < {threshold} hari"

            logger.info("Refresh token %s dipicu (%s)", platform, reason)

            try:
                plain_access_token = decrypt_token(record.access_token_encrypted)
                plain_refresh_token = (
                    decrypt_token(record.refresh_token_encrypted)
                    if record.refresh_token_encrypted
                    else None
                )
            except Exception as e:
                logger.error("Gagal mendekripsi token '%s': %s", platform, e)
                record.status = "error"
                record.last_error = f"Gagal dekripsi token: {e}"
                repo.save(record)
                return record

            try:
                ref_res = provider.refresh(record, plain_access_token, plain_refresh_token)
                record.access_token_encrypted = encrypt_token(ref_res.access_token)
                if ref_res.refresh_token is not None:
                    record.refresh_token_encrypted = encrypt_token(ref_res.refresh_token)
                record.issued_at = now
                record.expires_at = ref_res.expires_at
                record.last_refreshed_at = now
                record.expiry_estimated = False
                record.status = "active"
                record.last_error = None
                repo.save(record)
                logger.info("Refresh token %s berhasil, expires_at baru: %s", platform, ref_res.expires_at)
            except TokenInvalidError as e:
                logger.warning("Refresh token %s gagal (invalid): %s", platform, e)
                record.status = "needs_reconnect"
                record.last_error = str(e)
                repo.save(record)
            except TokenTransientError as e:
                logger.warning("Refresh token %s gagal (transient): %s", platform, e)
                record.last_error = str(e)
                repo.save(record)
            except Exception as e:
                logger.error("Refresh token %s gagal (tak terduga): %s", platform, e)
                record.last_error = str(e)
                repo.save(record)

            return record

    def run_startup_checks(self, session_factory: Callable[[], Session]) -> None:
        """Jalankan check_provider untuk seluruh provider terdaftar di background thread (daemon)."""
        def _worker() -> None:
            logger.info("Memulai startup check untuk token providers...")
            for platform in list(self._providers.keys()):
                try:
                    db = session_factory()
                    try:
                        self.check_provider(db, platform)
                    finally:
                        db.close()
                except Exception as e:
                    logger.exception("Startup check gagal untuk provider '%s': %s", platform, e)
            logger.info("Startup check token providers selesai.")

        t = threading.Thread(target=_worker, name="TokenManagerStartupChecks", daemon=True)
        t.start()

    def ensure_valid(self, db: Session, platform: str) -> OAuthTokenModel:
        """Validasi token sebelum dipakai, refresh bila perlu.

        Raise ValidationException berbahasa Indonesia bila token belum ada,
        berstatus needs_reconnect, atau sudah expired.
        """
        repo = OAuthTokenRepository(db)
        record = repo.get(platform)
        if not record:
            raise ValidationException(f"Token untuk platform '{platform}' belum dikonfigurasi.")

        now = datetime.now(timezone.utc)
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if record.status == "needs_reconnect":
            raise ValidationException(
                f"Token untuk platform '{platform}' perlu dihubungkan ulang. Silakan periksa kredensial."
            )

        if expires_at <= now:
            record.status = "needs_reconnect"
            record.last_error = "Token telah kedaluwarsa"
            repo.save(record)
            raise ValidationException(
                f"Token untuk platform '{platform}' telah kedaluwarsa. Silakan hubungkan ulang."
            )

        provider = self._providers.get(platform)
        if provider and record.status == "active" and provider.needs_refresh(record, now):
            lock = self._get_lock(platform)
            with lock:
                record = repo.get(platform)
                if not record:
                    raise ValidationException(f"Token untuk platform '{platform}' belum dikonfigurasi.")

                if provider.needs_refresh(record, now):
                    plain_access_token = decrypt_token(record.access_token_encrypted)
                    plain_refresh_token = (
                        decrypt_token(record.refresh_token_encrypted)
                        if record.refresh_token_encrypted
                        else None
                    )
                    try:
                        ref_res = provider.refresh(record, plain_access_token, plain_refresh_token)
                        record.access_token_encrypted = encrypt_token(ref_res.access_token)
                        if ref_res.refresh_token is not None:
                            record.refresh_token_encrypted = encrypt_token(ref_res.refresh_token)
                        record.issued_at = now
                        record.expires_at = ref_res.expires_at
                        record.last_refreshed_at = now
                        record.expiry_estimated = False
                        record.status = "active"
                        record.last_error = None
                        repo.save(record)
                    except TokenInvalidError as e:
                        record.status = "needs_reconnect"
                        record.last_error = str(e)
                        repo.save(record)
                        raise ValidationException(
                            f"Gagal memperbarui token platform '{platform}': {e}. Silakan hubungkan ulang."
                        )
                    except TokenTransientError as e:
                        logger.warning("Refresh token platform '%s' transient error di ensure_valid: %s", platform, e)
                        record.last_error = str(e)
                        repo.save(record)
                        if expires_at <= now:
                            raise ValidationException(
                                f"Token untuk platform '{platform}' kedaluwarsa dan gagal di-refresh: {e}"
                            )

        return record

    def get_access_token(self, db: Session, platform: str) -> str:
        """Ambil access token yang valid dan sudah didekripsi."""
        record = self.ensure_valid(db, platform)
        return decrypt_token(record.access_token_encrypted)

    def mark_needs_reconnect(self, db: Session, platform: str, reason: str) -> None:
        """Tandai token platform membutuhkan reconnect (misal saat API membalas 401/expired)."""
        repo = OAuthTokenRepository(db)
        record = repo.get(platform)
        if record:
            record.status = "needs_reconnect"
            record.last_error = reason
            repo.save(record)
            logger.warning("Token platform '%s' ditandai needs_reconnect: %s", platform, reason)

    def get_status(self, db: Session) -> list[dict]:
        """Ambil ringkasan status semua token yang tersimpan (tanpa token mentah)."""
        repo = OAuthTokenRepository(db)
        records = repo.list_all()
        now = datetime.now(timezone.utc)
        result = []
        for r in records:
            exp = r.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            diff_sec = (exp - now).total_seconds()
            days_left = max(0.0, round(diff_sec / 86400.0, 1))

            result.append({
                "platform": r.platform,
                "account_id": r.account_id,
                "status": r.status,
                "expires_at": r.expires_at,
                "days_left": days_left,
                "last_refreshed_at": r.last_refreshed_at,
                "last_validated_at": r.last_validated_at,
                "last_error": r.last_error,
                "expiry_estimated": r.expiry_estimated,
            })
        return result


_token_manager_instance: TokenManager | None = None
_instance_lock = threading.Lock()


def get_token_manager() -> TokenManager:
    """Ambil singleton instance TokenManager."""
    global _token_manager_instance
    if _token_manager_instance is None:
        with _instance_lock:
            if _token_manager_instance is None:
                _token_manager_instance = TokenManager()
    return _token_manager_instance
