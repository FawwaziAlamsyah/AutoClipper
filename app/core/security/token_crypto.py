"""Enkripsi/dekripsi token sensitif (OAuth access/refresh token) sebelum disimpan ke DB."""

from cryptography.fernet import Fernet

from app.core.config.settings import settings


def _get_fernet() -> Fernet:
    key = settings.TOKEN_ENCRYPTION_KEY or settings.TIKTOK_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY (atau TIKTOK_TOKEN_ENCRYPTION_KEY) belum di-set di .env — "
            "generate key dulu dengan Fernet sebelum menggunakan fitur token terenkripsi."
        )
    return Fernet(key.encode())


def encrypt_token(plain_token: str) -> str:
    """Enkripsi token sebelum disimpan ke database."""
    return _get_fernet().encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Dekripsi token yang tersimpan, dipakai saat mau panggil API TikTok."""
    return _get_fernet().decrypt(encrypted_token.encode()).decode()
