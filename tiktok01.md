# TikTok 01 — Schema Akun & Enkripsi Token

Bagian 1 dari 5 seri TikTok (kode). **Prasyarat: `tiktokSetup.md` sudah
selesai** (punya `client_key`/`client_secret`).

**Penting soal keamanan**: `access_token`/`refresh_token` TikTok itu
kredensial sensitif — kalau bocor, orang lain bisa post atas nama akun
TikTok Anda. **Tidak boleh disimpan sebagai teks polos di database.**

## Task — Dependency Baru

Tambahkan ke `requirements.txt`:

```
cryptography>=42.0
```

## Task — Setting Enkripsi & Kredensial TikTok

Di `app/core/config/settings.py`:

```python
TIKTOK_CLIENT_KEY: str = "sbawzgdj8957m738la"
TIKTOK_CLIENT_SECRET: str = "R8S9dcJQYc3y13J3n70XJlxEM5JtCqux"
TIKTOK_REDIRECT_URI: str = "http://localhost:8000/tiktok/oauth/callback"
TIKTOK_TOKEN_ENCRYPTION_KEY: str = "JwqzbfGQp6WmyFKEtKsOs6MSGfSohIyJq17XjgMIM48="  # generate sekali, simpan di .env (lihat instruksi di bawah)
```

Tambahkan ke `.env.example`:

```
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=http://localhost:8000/tiktok/oauth/callback
TIKTOK_TOKEN_ENCRYPTION_KEY=
```

**Generate `TIKTOK_TOKEN_ENCRYPTION_KEY` sekali** lewat terminal:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy hasilnya ke `.env` Anda (bukan `.env.example`). Kalau key ini hilang,
semua token yang sudah tersimpan tidak bisa didekripsi lagi (harus
connect ulang akun TikTok-nya).

## Task — Utility Enkripsi

`app/core/security/token_crypto.py` (file baru):

```python
"""Enkripsi/dekripsi token sensitif (OAuth access/refresh token) sebelum disimpan ke DB."""

from cryptography.fernet import Fernet

from app.core.config.settings import settings


def _get_fernet() -> Fernet:
    if not settings.TIKTOK_TOKEN_ENCRYPTION_KEY:
        raise ValueError(
            "TIKTOK_TOKEN_ENCRYPTION_KEY belum di-set di .env — generate dulu "
            "(lihat tiktok01.md) sebelum connect akun TikTok."
        )
    return Fernet(settings.TIKTOK_TOKEN_ENCRYPTION_KEY.encode())


def encrypt_token(plain_token: str) -> str:
    """Enkripsi token sebelum disimpan ke database."""
    return _get_fernet().encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Dekripsi token yang tersimpan, dipakai saat mau panggil API TikTok."""
    return _get_fernet().decrypt(encrypted_token.encode()).decode()
```

## Task — Tabel `tiktok_accounts`

### Migrasi Alembic baru

```
tiktok_accounts
├── id (PK)
├── open_id (string, unique — identifier user TikTok dari OAuth)
├── access_token_encrypted (text)
├── refresh_token_encrypted (text)
├── expires_at (datetime — kapan access_token kadaluwarsa)
├── created_at
└── updated_at
```

### `app/models/tiktok_account_model.py` (file baru)

```python
"""SQLAlchemy model untuk akun TikTok yang sudah connect via OAuth."""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TikTokAccountModel(Base):
    """Satu akun TikTok yang sudah di-connect lewat OAuth untuk publish clip."""

    __tablename__ = "tiktok_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    open_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

### `app/repositories/tiktok_account_repository.py` (file baru)

```python
"""Repository for TikTokAccountModel."""

from sqlalchemy.orm import Session

from app.models.tiktok_account_model import TikTokAccountModel


class TikTokAccountRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_first(self) -> TikTokAccountModel | None:
        """Ambil akun TikTok yang connect — app ini didesain untuk 1 akun personal,
        jadi cukup ambil yang pertama/satu-satunya, tidak perlu multi-akun.
        """
        return self.db.query(TikTokAccountModel).first()

    def get_by_open_id(self, open_id: str) -> TikTokAccountModel | None:
        return self.db.query(TikTokAccountModel).filter(TikTokAccountModel.open_id == open_id).first()

    def upsert(self, account: TikTokAccountModel) -> TikTokAccountModel:
        existing = self.get_by_open_id(account.open_id)
        if existing:
            existing.access_token_encrypted = account.access_token_encrypted
            existing.refresh_token_encrypted = account.refresh_token_encrypted
            existing.expires_at = account.expires_at
            self.db.commit()
            self.db.refresh(existing)
            return existing
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account
```

## Definisi Selesai

- Migrasi berhasil dijalankan, tabel `tiktok_accounts` ada.
- `TIKTOK_TOKEN_ENCRYPTION_KEY` sudah di-generate dan ada di `.env` (bukan
  cuma `.env.example`).
- Test manual: `from app.core.security.token_crypto import encrypt_token,
  decrypt_token; t = encrypt_token("test123"); print(decrypt_token(t))` →
  hasil `test123`, bukti roundtrip enkripsi jalan.
- `python -m py_compile app/core/security/token_crypto.py app/models/tiktok_account_model.py app/repositories/tiktok_account_repository.py`
  lulus.
- `pytest` tetap lulus.
- **Jangan lanjut ke `tiktok02.md`** sebelum poin di atas terverifikasi.
