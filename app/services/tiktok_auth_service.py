"""OAuth 2.0 flow untuk connect akun TikTok (Content Posting API).

TikTok WAJIB PKCE (RFC 7636): authorize URL harus bawa `code_challenge`
(S256) — tanpa itu TikTok tolak `code_challenge` di halaman login. Token
exchange harus bawa `code_verifier` yang sama. (Error "Code verifier or
code challenge is invalid" muncul pas kedua-duanya tidak cocok/salah.)"""

import base64
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

# Scope video.upload = "share sebagai draft" — post masuk akun TikTok user
# sebagai draft, lalu user tap post manual. Ini scope yang TIDAK butuh
# audit/review app (mode unaudited, sesuai tiktokSetup.md poin 5).
# video.publish (direct post) ditolak sandbox app di authorize dengan
# error "scope" — jangan dipakai sampai app lolos review.
SCOPES = "video.upload"

# CSRF + PKCE protection — state → code_verifier disimpan in-memory, cukup
# untuk app single-user lokal (bukan multi-tenant).
_pending_states: dict[str, str] = {}


def _b64_s256_unpadded(verifier: str) -> str:
    """PKCE S256 code_challenge, base64url TANPA padding (RFC 7636 wajib)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


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
        # code_challenge = S256 verifier, base64url TANPA padding (RFC 7636).
        # Verifier alphanumeric 64 char.
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
            logger.error("TikTok token error FULL body: %s", response.text)
            logger.error("CALLBACK verifier=%s challenge=%s", code_verifier, _b64_s256_unpadded(code_verifier))
            raise ValidationException(f"TikTok OAuth error: {response.text}")

        account = TikTokAccountModel(
            open_id=data["open_id"],
            access_token_encrypted=encrypt_token(data["access_token"]),
            refresh_token_encrypted=encrypt_token(data["refresh_token"]),
            expires_at=datetime.now(UTC) + timedelta(seconds=data["expires_in"]),
        )
        saved = self.repo.upsert(account)
        logger.info("Akun TikTok (open_id=%s) berhasil di-connect", saved.open_id)
        return saved

    def import_token(
        self,
        access_token: str,
        open_id: str | None = None,
        refresh_token: str = "",
        expires_in: int | None = None,
    ) -> TikTokAccountModel:
        """Import token manual langsung ke DB, skip OAuth (jalan sandbox yang tidak dipakai).

        Sandbox TikTok menolak PKCE exchange (lihat tiktok02.md) dan dashboard
        tidak punya token generator — jadi satu-satunya cara masuk token di mode
        belum-audit adalah paste manual lewat `POST /tiktok/admin/import`.
        """
        if not access_token:
            raise ValidationException("access_token wajib diisi.")

        if open_id is None:
            open_id = self._resolve_open_id(access_token)

        account = TikTokAccountModel(
            open_id=open_id,
            access_token_encrypted=encrypt_token(access_token),
            refresh_token_encrypted=encrypt_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in or 86400),
        )
        saved = self.repo.upsert(account)
        logger.info("TikTok token di-import manual (open_id=%s)", saved.open_id)
        return saved

    def _resolve_open_id(self, access_token: str) -> str:
        """Ambil open_id lewat user info — cuma jalan kalau token punya scope user.info.basic."""
        response = httpx.get(
            "https://open.tiktokapis.com/v2/user/info/?fields=open_id",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if response.status_code == 200:
            open_id = response.json().get("data", {}).get("open_id")
            if open_id:
                return open_id
        raise ValidationException(
            "open_id tidak bisa diambil otomatis (token tanpa scope user.info.basic) "
            "-- kirim open_id manual."
        )

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
