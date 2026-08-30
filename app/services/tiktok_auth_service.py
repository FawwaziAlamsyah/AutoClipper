"""OAuth 2.0 flow untuk connect akun TikTok (Content Posting API).

TikTok WAJIB PKCE (RFC 7636): authorize URL harus bawa `code_challenge`
(S256) — tanpa itu TikTok tolak `code_challenge` di halaman login. Token
exchange harus bawa `code_verifier` yang sama. (Error "Code verifier or
code challenge is invalid" muncul pas kedua-duanya tidak cocok/salah.)"""

import hashlib
import logging
import secrets
import string
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.core.security.token_crypto import encrypt_token, decrypt_token
from app.models.tiktok_account_model import TikTokAccountModel
from app.repositories.tiktok_account_repository import TikTokAccountRepository

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# Scope video.upload = upload ke inbox/draft user (endpoint
# /post/publish/inbox/video/init/). Video jadi draft private di inbox user,
# mereka selesaikan post manual dari app TikTok (mode unaudited, sesuai
# tiktokSetup.md poin 5). video.publish (Direct Post) butuh audit app —
# jangan dipakai sampai lolos review.
SCOPES = "video.upload"

# CSRF + PKCE protection — state → code_verifier disimpan in-memory, cukup
# untuk app single-user lokal (bukan multi-tenant).
_pending_states: dict[str, str] = {}


def _b64_s256_unpadded(verifier: str) -> str:
    """PKCE code_challenge buat TikTok.

    PENTING: TikTok TIDAK ikut RFC 7636 standar (base64url) di sini — untuk
    redirect_uri localhost/127.0.0.1 ("Desktop" platform type di TikTok),
    dokumentasi resmi mereka wajib HEX encoding dari SHA256 digest, bukan
    base64url. Ref: https://developers.tiktok.com/docs/en/login-kit-desktop
    ("You must use hex encoding of SHA256 to generate the code challenge").
    """
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


class TikTokAuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = TikTokAccountRepository(db)

    def build_authorize_url(self) -> str:
        """Buat URL buat user diarahkan login+izinkan akses di TikTok."""
        state = secrets.token_urlsafe(24)
        # PKCE wajib di TikTok (terbukti: authorize TANPA code_challenge ditolak
        # dengan error "code_challenge"), method HANYA literal "S256" uppercase
        # (PLAIN/lowercase ditolak dengan error "code_challenge_method").
        # Untuk platform type "Desktop" (redirect localhost), code_challenge =
        # HEX encoding dari SHA256 verifier — TIDAK pakai RFC 7636 base64url
        # (lihat _b64_s256_unpadded). Verifier alphanumeric 64 char.
        _alnum = string.ascii_letters + string.digits
        code_verifier = "".join(secrets.choice(_alnum) for _ in range(64))
        _pending_states[state] = code_verifier
        logger.debug("AUTHZ url state=%s verifier=%s", state, code_verifier)
        logger.error("AUTHZ challenge TO BE SENT: state=%s challenge=%s method=S256", state, _b64_s256_unpadded(code_verifier))
        return (
            f"{AUTHORIZE_URL}?client_key={settings.TIKTOK_CLIENT_KEY}"
            f"&scope={SCOPES}"
            f"&response_type=code"
            f"&redirect_uri={settings.TIKTOK_REDIRECT_URI}"
            f"&state={state}"
            f"&code_challenge={_b64_s256_unpadded(code_verifier)}"
            f"&code_challenge_method=S256"
        )

    def handle_callback(self, code: str, state: str) -> TikTokAccountModel:
        """Tukar authorization code dengan access/refresh token, simpan (terenkripsi)."""
        logger.debug("CALLBACK state=%s code=%s", state, code)
        code_verifier = _pending_states.pop(state, None)
        if code_verifier is None:
            raise ValidationException("State OAuth tidak valid — kemungkinan expired atau CSRF.")

        exchange_data = {
            "client_key": settings.TIKTOK_CLIENT_KEY,
            "client_secret": settings.TIKTOK_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.TIKTOK_REDIRECT_URI,
            "code_verifier": code_verifier,
            # redirect_uri WAJIB — tanpa itu TikTok tolak "malformed".
        }
        logger.debug(
            "EXCHANGE data -> client_key=%s code_len=%d redirect_uri=%s verifier=%s",
            settings.TIKTOK_CLIENT_KEY, len(code),
            settings.TIKTOK_REDIRECT_URI, code_verifier,
        )

        response = httpx.post(
            TOKEN_URL,
            data=exchange_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if response.status_code != 200:
            logger.error("TikTok token exchange gagal: %s", response.text)
            raise ValidationException(f"Gagal tukar token dengan TikTok: {response.text}")

        data = response.json()
        if "error" in data and data.get("error"):
            # Debug: log seluruh body error biar bisa lihat code/log_id TikTok
            logger.error("TikTok token error FULL body: %s", response.text)
            raise ValidationException(f"TikTok OAuth error: {data.get('error_description', data['error'])}")

        account = TikTokAccountModel(
            open_id=data["open_id"],
            access_token_encrypted=encrypt_token(data["access_token"]),
            refresh_token_encrypted=encrypt_token(data["refresh_token"]),
            expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
        )
        saved = self.repo.upsert(account)
        logger.info("Akun TikTok (open_id=%s) berhasil di-connect", saved.open_id)
        return saved

    def get_valid_access_token(self) -> str:
        """Ambil access_token yang valid — refresh otomatis kalau sudah/hampir kadaluwarsa."""
        account = self.repo.get_first()
        if account is None:
            raise ValidationException("Belum ada akun TikTok yang terhubung. Connect dulu lewat halaman Upload.")

        # Refresh kalau kurang dari 5 menit lagi kadaluwarsa
        if account.expires_at <= datetime.now(UTC) + timedelta(minutes=5):
            account = self._refresh_token(account)

        return decrypt_token(account.access_token_encrypted)

    def _refresh_token(self, account: TikTokAccountModel) -> TikTokAccountModel:
        refresh_token = decrypt_token(account.refresh_token_encrypted)
        if not refresh_token:
            raise ValidationException(
                "Refresh token tidak tersedia — token ini di-import manual. Import ulang token baru."
            )
        response = httpx.post(
            TOKEN_URL,
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if response.status_code != 200:
            raise ValidationException(
                "Gagal refresh token TikTok — kemungkinan perlu connect ulang akunnya."
            )
        data = response.json()
        account.access_token_encrypted = encrypt_token(data["access_token"])
        account.refresh_token_encrypted = encrypt_token(data["refresh_token"])
        account.expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])
        self.db.commit()
        self.db.refresh(account)
        logger.info("Token TikTok (open_id=%s) di-refresh", account.open_id)
        return account
