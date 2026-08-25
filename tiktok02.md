# TikTok 02 — OAuth Login & Callback

Bagian 2 dari 5. **Prasyarat: `tiktok01.md` sudah selesai.**

## Task — `TikTokAuthService`

`app/services/tiktok_auth_service.py` (file baru):

```python
"""OAuth 2.0 flow untuk connect akun TikTok (Content Posting API)."""

import logging
import secrets
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

# Scope video.publish wajib buat Content Posting API, user.info.basic buat
# ambil open_id/profil dasar.
SCOPES = "video.publish,user.info.basic"

# CSRF protection sederhana — state disimpan in-memory, cukup untuk app
# single-user lokal (bukan multi-tenant).
_pending_states: set[str] = set()


class TikTokAuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = TikTokAccountRepository(db)

    def build_authorize_url(self) -> str:
        """Buat URL buat user diarahkan login+izinkan akses di TikTok."""
        state = secrets.token_urlsafe(24)
        _pending_states.add(state)
        return (
            f"{AUTHORIZE_URL}?client_key={settings.TIKTOK_CLIENT_KEY}"
            f"&scope={SCOPES}"
            f"&response_type=code"
            f"&redirect_uri={settings.TIKTOK_REDIRECT_URI}"
            f"&state={state}"
        )

    def handle_callback(self, code: str, state: str) -> TikTokAccountModel:
        """Tukar authorization code dengan access/refresh token, simpan (terenkripsi)."""
        if state not in _pending_states:
            raise ValidationException("State OAuth tidak valid — kemungkinan expired atau CSRF.")
        _pending_states.discard(state)

        response = httpx.post(
            TOKEN_URL,
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.TIKTOK_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if response.status_code != 200:
            logger.error("TikTok token exchange gagal: %s", response.text)
            raise ValidationException(f"Gagal tukar token dengan TikTok: {response.text}")

        data = response.json()
        if "error" in data and data.get("error"):
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
```

Tambahkan `httpx` ke `requirements.txt` kalau belum ada (kemungkinan sudah
ada, dipakai test — cek dulu sebelum nambah duplikat).

## Task — Router OAuth

`app/routers/tiktok_router.py` (file baru):

```python
"""OAuth & publish endpoints untuk integrasi TikTok."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.core.di.dependencies import get_tiktok_auth_service
from app.services.tiktok_auth_service import TikTokAuthService

router = APIRouter(prefix="/tiktok", tags=["tiktok"])


@router.get("/oauth/login")
def tiktok_oauth_login(service: TikTokAuthService = Depends(get_tiktok_auth_service)):
    """Redirect user ke halaman login+izin TikTok."""
    return RedirectResponse(service.build_authorize_url())


@router.get("/oauth/callback")
def tiktok_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    service: TikTokAuthService = Depends(get_tiktok_auth_service),
):
    """TikTok redirect ke sini setelah user login+izinkan akses."""
    account = service.handle_callback(code, state)
    return RedirectResponse(f"/upload?tiktok_connected=1&open_id={account.open_id}")
```

Tambahkan `get_tiktok_auth_service` di `dependencies.py`, dan daftarkan
`tiktok_router` di `app/main.py` (pola sama seperti router lain).

## Definisi Selesai

- `python -m py_compile app/services/tiktok_auth_service.py app/routers/tiktok_router.py`
  lulus.
- Buka `http://localhost:8000/tiktok/oauth/login` di browser → redirect ke
  halaman login TikTok (bukti `build_authorize_url()` benar).
- Login + izinkan akses di TikTok → redirect balik ke
  `/upload?tiktok_connected=1&open_id=...` → cek database, row baru ada di
  `tiktok_accounts`, `access_token_encrypted` BUKAN teks polos (harus
  kelihatan random/terenkripsi kalau dibuka manual).
- `pytest` tetap lulus.
- **Jangan lanjut ke `tiktok03.md`** sebelum poin di atas terverifikasi
  (butuh app TikTok Anda beneran aktif dari `tiktokSetup.md`).
