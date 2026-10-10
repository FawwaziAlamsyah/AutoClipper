"""Unit tests untuk InstagramTokenProvider, seed, validate, refresh, dan status router."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
import httpx
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.core.config.settings import settings
from app.core.security.token_crypto import decrypt_token, encrypt_token
from app.db.session import get_db
from app.main import app
from app.models.oauth_token_model import OAuthTokenModel
from app.repositories.oauth_token_repository import OAuthTokenRepository
from app.services.token_manager.base import (
    TokenInvalidError,
    TokenTransientError,
)
from app.services.token_manager.instagram_provider import InstagramTokenProvider
from app.services.token_manager.manager import TokenManager
from app.services.token_manager.setup import build_default_manager


@pytest.fixture(autouse=True)
def setup_test_crypto_key():
    """Pastikan TOKEN_ENCRYPTION_KEY terpasang untuk unit test."""
    test_key = Fernet.generate_key().decode()
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", test_key):
        yield


@pytest.fixture(autouse=True)
def clean_oauth_tokens(db_session: Session):
    """Bersihkan oauth_tokens di awal setiap test transaksi."""
    db_session.query(OAuthTokenModel).delete()
    yield


@pytest.fixture
def provider() -> InstagramTokenProvider:
    return InstagramTokenProvider()


# ── Test sync_from_config (Seed) ──────────────────────────────────────────────

def test_sync_from_config_empty_settings_does_nothing(db_session: Session, provider: InstagramTokenProvider):
    with patch.object(settings, "IG_ACCESS_TOKEN", ""), patch.object(settings, "IG_USER_ID", ""):
        provider.sync_from_config(db_session)
        repo = OAuthTokenRepository(db_session)
        assert repo.list_all() == []


def test_sync_from_config_first_seed_with_issued_at(db_session: Session, provider: InstagramTokenProvider):
    issued_iso = "2026-10-01T10:00:00+00:00"
    with patch.object(settings, "IG_ACCESS_TOKEN", "dummy-ig-access-token-1"), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_TOKEN_ISSUED_AT", issued_iso), \
         patch.object(settings, "IG_TOKEN_LIFETIME_DAYS", 60):
        provider.sync_from_config(db_session)

        repo = OAuthTokenRepository(db_session)
        rec = repo.get("instagram", "17841400000000001")
        assert rec is not None
        assert rec.platform == "instagram"
        assert rec.account_id == "17841400000000001"
        assert decrypt_token(rec.access_token_encrypted) == "dummy-ig-access-token-1"
        assert rec.expiry_estimated is False
        assert rec.issued_at == datetime.fromisoformat(issued_iso)
        assert rec.expires_at == rec.issued_at + timedelta(days=60)
        assert rec.status == "active"
        assert rec.seed_fingerprint is not None


def test_sync_from_config_first_seed_without_issued_at(db_session: Session, provider: InstagramTokenProvider):
    with patch.object(settings, "IG_ACCESS_TOKEN", "dummy-ig-access-token-1"), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_TOKEN_ISSUED_AT", ""), \
         patch.object(settings, "IG_TOKEN_LIFETIME_DAYS", 60):
        provider.sync_from_config(db_session)

        repo = OAuthTokenRepository(db_session)
        rec = repo.get("instagram", "17841400000000001")
        assert rec is not None
        assert rec.expiry_estimated is True
        assert rec.status == "active"
        assert rec.expires_at > datetime.now(timezone.utc) + timedelta(days=59)


def test_sync_from_config_same_fingerprint_preserves_db_token(db_session: Session, provider: InstagramTokenProvider):
    # Seed awal
    with patch.object(settings, "IG_ACCESS_TOKEN", "dummy-ig-access-token-1"), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_TOKEN_ISSUED_AT", "2026-10-01T00:00:00Z"):
        provider.sync_from_config(db_session)

    repo = OAuthTokenRepository(db_session)
    rec = repo.get("instagram", "17841400000000001")
    assert rec is not None

    # Simulasikan token di DB telah di-refresh dengan token baru
    rec.access_token_encrypted = encrypt_token("dummy-refreshed-access-token")
    rec.last_refreshed_at = datetime.now(timezone.utc)
    repo.save(rec)

    # Jalankan sync_from_config lagi dengan IG_ACCESS_TOKEN yang sama di .env
    with patch.object(settings, "IG_ACCESS_TOKEN", "dummy-ig-access-token-1"), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_TOKEN_ISSUED_AT", "2026-10-01T00:00:00Z"):
        provider.sync_from_config(db_session)

    # Token di DB tidak boleh tertimpa kembali ke dummy-ig-access-token-1
    rec_after = repo.get("instagram", "17841400000000001")
    assert decrypt_token(rec_after.access_token_encrypted) == "dummy-refreshed-access-token"


def test_sync_from_config_different_fingerprint_overwrites(db_session: Session, provider: InstagramTokenProvider):
    # Seed awal
    with patch.object(settings, "IG_ACCESS_TOKEN", "dummy-ig-access-token-1"), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"):
        provider.sync_from_config(db_session)

    repo = OAuthTokenRepository(db_session)
    rec = repo.get("instagram", "17841400000000001")
    rec.status = "needs_reconnect"
    rec.last_error = "Old invalid error"
    repo.save(rec)

    # User memperbarui .env dengan token baru
    with patch.object(settings, "IG_ACCESS_TOKEN", "dummy-ig-access-token-2"), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_TOKEN_ISSUED_AT", "2026-10-05T00:00:00Z"):
        provider.sync_from_config(db_session)

    rec_updated = repo.get("instagram", "17841400000000001")
    assert decrypt_token(rec_updated.access_token_encrypted) == "dummy-ig-access-token-2"
    assert rec_updated.status == "active"
    assert rec_updated.last_error is None


# ── Test needs_refresh ────────────────────────────────────────────────────────

def test_needs_refresh_inactive_status(provider: InstagramTokenProvider):
    now = datetime.now(timezone.utc)
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        issued_at=now - timedelta(days=40),
        expires_at=now + timedelta(days=5),
        expiry_estimated=False,
        status="needs_reconnect",
    )
    assert provider.needs_refresh(rec, now) is False


@pytest.mark.parametrize("days_left", [50, 20, 6])
def test_needs_refresh_remaining_50_20_6_days_returns_false(provider: InstagramTokenProvider, days_left: int):
    now = datetime.now(timezone.utc)
    # Default IG_TOKEN_REFRESH_BEFORE_DAYS = 5. Sisa 50, 20, 6 hari -> False
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        issued_at=now - timedelta(days=40),
        expires_at=now + timedelta(days=days_left),
        expiry_estimated=False,
        status="active",
    )
    with patch.object(settings, "IG_TOKEN_REFRESH_BEFORE_DAYS", 5), \
         patch.object(settings, "IG_TOKEN_MIN_AGE_HOURS", 24):
        assert provider.needs_refresh(rec, now) is False


def test_needs_refresh_remaining_4_days_age_over_24h_returns_true(provider: InstagramTokenProvider):
    now = datetime.now(timezone.utc)
    # Sisa 4 hari (< 5) dan umur 30 jam (>= 24) -> True
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        issued_at=now - timedelta(hours=30),
        expires_at=now + timedelta(days=4),
        expiry_estimated=False,
        status="active",
    )
    with patch.object(settings, "IG_TOKEN_REFRESH_BEFORE_DAYS", 5), \
         patch.object(settings, "IG_TOKEN_MIN_AGE_HOURS", 24):
        assert provider.needs_refresh(rec, now) is True


def test_needs_refresh_remaining_4_days_age_under_24h_returns_false(provider: InstagramTokenProvider):
    now = datetime.now(timezone.utc)
    # Sisa 4 hari (< 5) tapi umur baru 12 jam (< 24) -> False
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        issued_at=now - timedelta(hours=12),
        expires_at=now + timedelta(days=4),
        expiry_estimated=False,
        status="active",
    )
    with patch.object(settings, "IG_TOKEN_REFRESH_BEFORE_DAYS", 5), \
         patch.object(settings, "IG_TOKEN_MIN_AGE_HOURS", 24):
        assert provider.needs_refresh(rec, now) is False


def test_needs_refresh_expiry_estimated_returns_true(provider: InstagramTokenProvider):
    now = datetime.now(timezone.utc)
    # Bila expiry_estimated=True, langsung return True (cek umur dilewati)
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        issued_at=now,
        expires_at=now + timedelta(days=60),
        expiry_estimated=True,
        status="active",
    )
    assert provider.needs_refresh(rec, now) is True


def test_check_provider_healthy_token_makes_zero_http_calls(db_session: Session, provider: InstagramTokenProvider):
    """Sisa 50 hari -> check_provider tidak melakukan HTTP call sama sekali."""
    now = datetime.now(timezone.utc)
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400000000001",
        access_token_encrypted=encrypt_token("dummy-access-token"),
        issued_at=now - timedelta(days=10),
        expires_at=now + timedelta(days=50),
        expiry_estimated=False,
        status="active",
    )
    OAuthTokenRepository(db_session).upsert(rec)

    manager = TokenManager()
    manager.register(provider)

    with patch("httpx.get") as mock_get:
        manager.check_provider(db_session, "instagram")
        mock_get.assert_not_called()


def test_check_provider_expiry_estimated_refreshes_once_and_clears_flag(db_session: Session, provider: InstagramTokenProvider):
    """Record expiry_estimated=True di-refresh sekali, flag menjadi False, run berikutnya skip."""
    now = datetime.now(timezone.utc)
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400000000001",
        access_token_encrypted=encrypt_token("dummy-short-token"),
        issued_at=now,
        expires_at=now + timedelta(days=60),
        expiry_estimated=True,
        status="active",
    )
    OAuthTokenRepository(db_session).upsert(rec)

    manager = TokenManager()
    manager.register(provider)

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"access_token": "dummy-new-token-from-refresh", "expires_in": 5184000}

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        # Run 1: refresh dipanggil karena expiry_estimated=True
        r1 = manager.check_provider(db_session, "instagram")
        assert r1.expiry_estimated is False
        assert mock_get.call_count == 1

        # Run 2: tidak refresh lagi karena expiry_estimated sudah False dan sisa 60 hari
        r2 = manager.check_provider(db_session, "instagram")
        assert r2.expiry_estimated is False
        assert mock_get.call_count == 1  # Tetap 1, tidak ada call tambahan


# ── Test validate ─────────────────────────────────────────────────────────────

def test_validate_success(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "user_id": "17841400001",
        "username": "awesome_creator",
        "account_type": "BUSINESS",
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.validate(rec, "dummy-access-token")
        assert res.ok is True
        assert res.account_label == "awesome_creator"


def test_validate_mismatched_user_id(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "user_id": "99999999999",
        "username": "other_account",
        "account_type": "BUSINESS",
    }

    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(TokenInvalidError, match="tidak cocok"):
            provider.validate(rec, "dummy-access-token")


def test_validate_personal_account_type_rejected(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "user_id": "17841400001",
        "username": "personal_user",
        "account_type": "PERSONAL",
    }

    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(TokenInvalidError, match="Professional"):
            provider.validate(rec, "dummy-access-token")


def test_validate_error_code_190(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": {
            "message": "Error validating access token: Session has expired.",
            "type": "OAuthException",
            "code": 190,
        }
    }

    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(TokenInvalidError, match="code 190"):
            provider.validate(rec, "dummy-access-token")


def test_validate_timeout_raises_transient(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    with patch("httpx.get", side_effect=httpx.ReadTimeout("Request timed out")):
        with pytest.raises(TokenTransientError, match="Timeout"):
            provider.validate(rec, "dummy-access-token")


def test_validate_server_500_raises_transient(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.json.return_value = {}

    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(TokenTransientError, match="server error"):
            provider.validate(rec, "dummy-access-token")


# ── Test refresh ──────────────────────────────────────────────────────────────

def test_refresh_success(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "dummy-new-refreshed-token",
        "token_type": "bearer",
        "expires_in": 5184000,  # 60 hari
    }

    with patch("httpx.get", return_value=mock_resp):
        res = provider.refresh(rec, "dummy-old-token", None)
        assert res.access_token == "dummy-new-refreshed-token"
        assert res.expires_at > datetime.now(timezone.utc) + timedelta(days=59)


def test_refresh_error_code_190(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": {
            "message": "The access token could not be decrypted",
            "type": "IGApiException",
            "code": 190,
        }
    }

    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(TokenInvalidError, match="code 190"):
            provider.refresh(rec, "dummy-old-token", None)


def test_refresh_transient_error(provider: InstagramTokenProvider):
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400001",
        access_token_encrypted="enc",
        status="active",
    )

    with patch("httpx.get", side_effect=httpx.ConnectError("Failed to connect")):
        with pytest.raises(TokenTransientError, match="Koneksi gagal"):
            provider.refresh(rec, "dummy-old-token", None)


# ── Test GET /tokens/status endpoint ──────────────────────────────────────────

def test_tokens_status_endpoint(db_session: Session):
    # Buat record token Instagram di DB
    now = datetime.now(timezone.utc)
    rec = OAuthTokenModel(
        platform="instagram",
        account_id="17841400000000001",
        access_token_encrypted=encrypt_token("dummy-ig-access-token"),
        issued_at=now - timedelta(days=10),
        expires_at=now + timedelta(days=50),
        expiry_estimated=False,
        status="active",
    )
    repo = OAuthTokenRepository(db_session)
    repo.upsert(rec)

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        resp = client.get("/tokens/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "tokens" in data
        tokens = data["tokens"]
        assert len(tokens) >= 1
        ig_token = next((t for t in tokens if t["platform"] == "instagram"), None)
        assert ig_token is not None
        assert ig_token["account_id"] == "17841400000000001"
        assert ig_token["status"] == "active"
        assert ig_token["days_left"] > 45
        assert "access_token" not in ig_token  # Memastikan token mentah tidak bocor
    finally:
        app.dependency_overrides.pop(get_db, None)
