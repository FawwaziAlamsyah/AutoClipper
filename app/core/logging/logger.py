"""Logging setup.

Strategi: log proses terlihat di terminal (console). File error.log tetap
untuk jejak error saja. Tidak ada app.log/performance.log — user minta
monitor proses via terminal, bukan file terpisah.
"""

import logging
import logging.handlers
from pathlib import Path

from app.core.config.settings import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_MAX_BYTES = 5_000_000
_BACKUP_COUNT = 5


def setup_logging() -> None:
    """Configure root logger: console (semua level) + error.log (ERROR+)."""
    log_dir: Path = settings.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)
    root_logger.handlers.clear()

    # Console — tempat user melihat progress proses secara realtime.
    # Level DEBUG agar pesan log.debug("...") dari tiap proses terlihat.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # error.log — hanya error, agar ada jejak di disk.
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # Matikan uvicorn access log (polling UI menyebabkan spam GET /jobs/xxx setiap detik).
    # Log error uvicorn tetap jalan — hanya access log per-request yang dimatikan.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
