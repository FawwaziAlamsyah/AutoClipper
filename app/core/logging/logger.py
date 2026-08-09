"""Logging setup.

Memisahkan log menjadi tiga file berdasarkan tujuan:
- app.log         : alur normal aplikasi (INFO ke atas)
- error.log       : hanya error & exception (ERROR ke atas)
- performance.log : metrik durasi eksekusi
"""

import logging
import logging.handlers
from pathlib import Path

from app.core.config.settings import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

PERFORMANCE_LOGGER_NAME = "performance"

_MAX_BYTES = 5_000_000
_BACKUP_COUNT = 5


def setup_logging() -> None:
    """Configure root, error, and performance log handlers.

    Dipanggil sekali saat aplikasi start up (lihat app/main.py).
    """
    log_dir: Path = settings.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)
    root_logger.handlers.clear()

    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)
    root_logger.addHandler(app_handler)

    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    performance_logger = logging.getLogger(PERFORMANCE_LOGGER_NAME)
    performance_logger.setLevel(logging.INFO)
    performance_logger.propagate = False
    performance_logger.handlers.clear()
    performance_handler = logging.handlers.RotatingFileHandler(
        log_dir / "performance.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    performance_handler.setFormatter(formatter)
    performance_logger.addHandler(performance_handler)


def get_performance_logger() -> logging.Logger:
    """Return the dedicated performance logger (menulis ke performance.log)."""
    return logging.getLogger(PERFORMANCE_LOGGER_NAME)
