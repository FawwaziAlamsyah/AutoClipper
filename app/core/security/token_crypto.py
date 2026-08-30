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
