"""Inisialisasi default TokenManager dan pendaftaran provider bawaan."""

import logging
import threading

from app.services.token_manager.instagram_provider import InstagramTokenProvider
from app.services.token_manager.manager import TokenManager, get_token_manager

logger = logging.getLogger(__name__)

_initialized = False
_setup_lock = threading.Lock()


def build_default_manager() -> TokenManager:
    """Buat dan daftarkan provider bawaan ke TokenManager singleton secara idempoten."""
    global _initialized
    manager = get_token_manager()
    if not _initialized:
        with _setup_lock:
            if not _initialized:
                if manager.get_provider("instagram") is None:
                    manager.register(InstagramTokenProvider())
                _initialized = True
    return manager
