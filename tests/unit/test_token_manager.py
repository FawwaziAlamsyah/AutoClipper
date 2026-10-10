"""Unit tests untuk TokenManager, OAuthTokenRepository, token_crypto, dan log masking."""

from datetime import datetime, timedelta, timezone
import logging
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
import pytest
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.core.logging.masking import SecretMaskingFilter, mask_secrets
from app.core.security.token_crypto import _get_fernet, decrypt_token, encrypt_token
from app.models.oauth_token_model import OAuthTokenModel
from app.repositories.oauth_token_repository import OAuthTokenRepository
from app.services.token_manager.base import (
    RefreshResult,
    TokenInvalidError,
    TokenProvider,
    TokenTransientError,
    ValidationResult,
)
from app.services.token_manager.manager import TokenManager


# ── FakeProvider untuk Pengujian ──────────────────────────────────────────────

class FakeProvider(TokenProvider):
    def __init__(self, platform: str = "fake_platform") -> None:
        self.platform = platform
        self.validate_calls: int = 0
        self.refresh_calls: int = 0
        self.should_need_refresh: bool = False
        self.validate_error: Exception | None = None
        self.refresh_error: Exception | None = None
        self.next_refresh_token: str = "new-access-token"
        self.next_refresh_expires_in_hours: int = 24

    def needs_refresh(self, record: OAuthTokenModel, now: datetime) -> bool:
        return self.should_need_refresh

    def validate(self, record: OAuthTokenModel, access_token: str) -> ValidationResult:
        self.validate_calls += 1
        if self.validate_error:
            raise self.validate_error
        return ValidationResult(ok=True, account_label="test_user")

    def refresh(
        self, record: OAuthTokenModel, access_token: str, refresh_token: str | None
    ) -> RefreshResult:
        self.refresh_calls += 1
        if self.refresh_error:
            raise self.refresh_error
        return RefreshResult(
            access_token=self.next_refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=self.next_refresh_expires_in_hours),
            refresh_token="new-refresh-token",
        )


@pytest.fixture(autouse=True)
def setup_test_crypto_key():
    """Pastikan TOKEN_ENCRYPTION_KEY terpasang untuk unit test."""
    test_key = Fernet.generate_key().decode()
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", test_key):
        yield


def _create_token_record(
    db: Session,
    platform: str = "fake_platform",
    account_id: str = "acc_1",
    status: str = "active",
    expires_in_hours: int = 48,
    raw_token: str = "initial-access-token",
) -> OAuthTokenModel:
    now = datetime.now(timezone.utc)
    rec = OAuthTokenModel(
        platform=platform,
        account_id=account_id,
        access_token_encrypted=encrypt_token(raw_token),
        refresh_token_encrypted=encrypt_token("initial-refresh-token"),
        issued_at=now,
        expires_at=now + timedelta(hours=expires_in_hours),
        expiry_estimated=False,
        status=status,
    )
    repo = OAuthTokenRepository(db)
    return repo.upsert(rec)


# ── Test token_crypto ─────────────────────────────────────────────────────────

def test_token_crypto_uses_token_encryption_key():
    test_key = Fernet.generate_key().decode()
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", test_key), \
         patch.object(settings, "TIKTOK_TOKEN_ENCRYPTION_KEY", ""):
        encrypted = encrypt_token("secret-hello")
        decrypted = decrypt_token(encrypted)
        assert decrypted == "secret-hello"


def test_token_crypto_fallback_to_tiktok_key():
    tiktok_key = Fernet.generate_key().decode()
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", ""), \
         patch.object(settings, "TIKTOK_TOKEN_ENCRYPTION_KEY", tiktok_key):
        encrypted = encrypt_token("secret-tiktok-fallback")
        decrypted = decrypt_token(encrypted)
        assert decrypted == "secret-tiktok-fallback"


def test_token_crypto_raises_when_both_keys_empty():
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", ""), \
         patch.object(settings, "TIKTOK_TOKEN_ENCRYPTION_KEY", ""):
        with pytest.raises(ValueError, match="TOKEN_ENCRYPTION_KEY"):
            _get_fernet()


# ── Test OAuthTokenRepository ─────────────────────────────────────────────────

def test_oauth_token_repository_crud(db_session: Session):
    repo = OAuthTokenRepository(db_session)
    now = datetime.now(timezone.utc)

    # Upsert new
    rec = OAuthTokenModel(
        platform="test_crud",
        account_id="user_1",
        access_token_encrypted="enc_token_1",
        issued_at=now,
        expires_at=now + timedelta(days=30),
        status="active",
    )
    saved = repo.upsert(rec)
    assert saved.id is not None
    assert saved.platform == "test_crud"

    # Get by platform & account
    found = repo.get("test_crud", "user_1")
    assert found is not None
    assert found.id == saved.id

    # Get by platform only (ambil yang pertama)
    found_first = repo.get("test_crud")
    assert found_first is not None
    assert found_first.account_id == "user_1"

    # Upsert existing (update)
    rec2 = OAuthTokenModel(
        platform="test_crud",
        account_id="user_1",
        access_token_encrypted="enc_token_updated",
        issued_at=now,
        expires_at=now + timedelta(days=60),
        status="active",
    )
    updated = repo.upsert(rec2)
    assert updated.id == saved.id
    assert updated.access_token_encrypted == "enc_token_updated"


# ── Test TokenManager ─────────────────────────────────────────────────────────

def test_token_valid_no_refresh_needed(db_session: Session):
    """Token valid dan belum butuh refresh -> validate & refresh TIDAK dipanggil (nol panggilan jaringan)."""
    provider = FakeProvider(platform="fake_platform")
    provider.should_need_refresh = False
    _create_token_record(db_session, platform="fake_platform")

    manager = TokenManager()
    manager.register(provider)

    record = manager.check_provider(db_session, "fake_platform")
    assert record is not None
    assert record.status == "active"
    assert provider.validate_calls == 0
    assert provider.refresh_calls == 0


def test_token_valid_refresh_triggered(db_session: Session):
    """Token valid & needs_refresh=True -> refresh dipanggil tanpa validate rutin, token baru tersimpan."""
    provider = FakeProvider(platform="fake_platform")
    provider.should_need_refresh = True
    provider.next_refresh_token = "refreshed-token-xyz"
    _create_token_record(db_session, platform="fake_platform", raw_token="old-token")

    manager = TokenManager()
    manager.register(provider)

    record = manager.check_provider(db_session, "fake_platform")
    assert record is not None
    assert record.status == "active"
    assert provider.validate_calls == 0
    assert provider.refresh_calls == 1
    assert record.last_refreshed_at is not None
    assert decrypt_token(record.access_token_encrypted) == "refreshed-token-xyz"


def test_validate_token_invalid_error():
    """TokenInvalidError saat pemanggilan validate manual."""
    provider = FakeProvider(platform="fake_platform")
    provider.validate_error = TokenInvalidError("Token revoked by user")
    rec = OAuthTokenModel(platform="fake_platform", account_id="acc_1", access_token_encrypted="enc", status="active")
    with pytest.raises(TokenInvalidError, match="Token revoked by user"):
        provider.validate(rec, "dummy-token")


def test_validate_token_transient_error():
    """TokenTransientError saat pemanggilan validate manual."""
    provider = FakeProvider(platform="fake_platform")
    provider.validate_error = TokenTransientError("Network timeout")
    rec = OAuthTokenModel(platform="fake_platform", account_id="acc_1", access_token_encrypted="enc", status="active")
    with pytest.raises(TokenTransientError, match="Network timeout"):
        provider.validate(rec, "dummy-token")


def test_check_provider_run_twice_with_healthy_token_zero_network_calls(db_session: Session):
    """Startup dijalankan dua kali berturut-turut dengan token sehat -> nol panggilan jaringan pada keduanya."""
    provider = FakeProvider(platform="fake_platform")
    provider.should_need_refresh = False
    _create_token_record(db_session, platform="fake_platform", expires_in_hours=720)

    manager = TokenManager()
    manager.register(provider)

    # Run 1
    rec1 = manager.check_provider(db_session, "fake_platform")
    assert rec1 is not None
    assert provider.validate_calls == 0
    assert provider.refresh_calls == 0

    # Run 2
    rec2 = manager.check_provider(db_session, "fake_platform")
    assert rec2 is not None
    assert provider.validate_calls == 0
    assert provider.refresh_calls == 0


def test_ensure_valid_does_not_call_validate(db_session: Session):
    """ensure_valid hanya melakukan pemeriksaan lokal dan tidak memanggil validate()."""
    provider = FakeProvider(platform="fake_platform")
    provider.should_need_refresh = False
    _create_token_record(db_session, platform="fake_platform", expires_in_hours=720)

    manager = TokenManager()
    manager.register(provider)

    rec = manager.ensure_valid(db_session, "fake_platform")
    assert rec.status == "active"
    assert provider.validate_calls == 0


def test_refresh_token_invalid_error(db_session: Session):
    """TokenInvalidError saat refresh -> status needs_reconnect."""
    provider = FakeProvider(platform="fake_platform")
    provider.should_need_refresh = True
    provider.refresh_error = TokenInvalidError("Refresh token expired")
    _create_token_record(db_session, platform="fake_platform")

    manager = TokenManager()
    manager.register(provider)

    record = manager.check_provider(db_session, "fake_platform")
    assert record is not None
    assert record.status == "needs_reconnect"
    assert "Refresh token expired" in (record.last_error or "")


def test_refresh_token_transient_error(db_session: Session):
    """TokenTransientError saat refresh -> status tetap active, last_error terisi."""
    provider = FakeProvider(platform="fake_platform")
    provider.should_need_refresh = True
    provider.refresh_error = TokenTransientError("503 Service Unavailable")
    _create_token_record(db_session, platform="fake_platform")

    manager = TokenManager()
    manager.register(provider)

    record = manager.check_provider(db_session, "fake_platform")
    assert record is not None
    assert record.status == "active"
    assert "503 Service Unavailable" in (record.last_error or "")


def test_run_startup_checks_isolates_provider_errors():
    """Error fatal pada satu provider tidak menghentikan provider lain di startup check."""
    prov_error = FakeProvider(platform="p_error")
    prov_error.validate = MagicMock(side_effect=RuntimeError("Crash unhandled"))

    prov_ok = FakeProvider(platform="p_ok")

    manager = TokenManager()
    manager.register(prov_error)
    manager.register(prov_ok)

    mock_db = MagicMock()
    mock_factory = MagicMock(return_value=mock_db)

    # Jalankan langsung thread worker secara synchronous untuk assertion
    threads = []
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        manager.run_startup_checks(mock_factory)

        # Target worker
        worker = mock_thread_cls.call_args.kwargs["target"]
        with patch.object(manager, "check_provider") as mock_check:
            def _fake_check(db, plat):
                if plat == "p_error":
                    raise RuntimeError("Crash provider 1")
                return None
            mock_check.side_effect = _fake_check
            worker()

            # Pastikan kedua provider tetap dipanggil
            assert mock_check.call_count == 2


def test_ensure_valid_validations(db_session: Session):
    """ensure_valid menolak record kosong, needs_reconnect, dan token kedaluwarsa."""
    manager = TokenManager()

    # 1. Kosong
    with pytest.raises(ValidationException, match="belum dikonfigurasi"):
        manager.ensure_valid(db_session, "non_existent")

    # 2. Status needs_reconnect
    _create_token_record(db_session, platform="plat_reconn", status="needs_reconnect")
    with pytest.raises(ValidationException, match="perlu dihubungkan ulang"):
        manager.ensure_valid(db_session, "plat_reconn")

    # 3. Expired
    _create_token_record(db_session, platform="plat_exp", expires_in_hours=-5)
    with pytest.raises(ValidationException, match="telah kedaluwarsa"):
        manager.ensure_valid(db_session, "plat_exp")

    # 4. Valid token
    _create_token_record(db_session, platform="plat_ok", expires_in_hours=24, raw_token="my-valid-token")
    rec = manager.ensure_valid(db_session, "plat_ok")
    assert rec.platform == "plat_ok"
    assert manager.get_access_token(db_session, "plat_ok") == "my-valid-token"


def test_mark_needs_reconnect_and_get_status(db_session: Session):
    manager = TokenManager()
    _create_token_record(db_session, platform="plat_status", account_id="acc_99")

    # Mark needs reconnect
    manager.mark_needs_reconnect(db_session, "plat_status", "Invalid OAuth session")
    statuses = manager.get_status(db_session)

    stat = next(s for s in statuses if s["platform"] == "plat_status")
    assert stat["status"] == "needs_reconnect"
    assert stat["last_error"] == "Invalid OAuth session"
    assert stat["account_id"] == "acc_99"
    assert stat["days_left"] >= 1.0


# ── Test Masking Filter ───────────────────────────────────────────────────────

def test_mask_secrets_function():
    # access_token query param
    text1 = "https://graph.instagram.com/me?access_token=EAABwz918237xyz&fields=id"
    assert mask_secrets(text1) == "https://graph.instagram.com/me?access_token=***&fields=id"

    # refresh_token
    text2 = "POST /refresh with refresh_token=rfr_secret_123 in body"
    assert mask_secrets(text2) == "POST /refresh with refresh_token=*** in body"

    # client_secret
    text3 = "client_secret=super_secret_999"
    assert mask_secrets(text3) == "client_secret=***"

    # Bearer header
    text4 = "Headers: Authorization: Bearer IGAAbc123Token..."
    assert mask_secrets(text4) == "Headers: Authorization: Bearer ***"

    # OAuth header
    text5 = "Headers: Authorization: OAuth EAABc123..."
    assert mask_secrets(text5) == "Headers: Authorization: OAuth ***"


def test_secret_masking_filter_in_logger():
    filter_obj = SecretMaskingFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Calling graph API with access_token=%s and Bearer %s",
        args=("secret_token_1", "secret_token_2"),
        exc_info=None,
    )
    result = filter_obj.filter(record)
    assert result is True
    assert "secret_token_1" not in record.msg
    assert "secret_token_2" not in record.msg
    assert "access_token=***" in record.msg
    assert "Bearer ***" in record.msg
    assert record.args == ()
