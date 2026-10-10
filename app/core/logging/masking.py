"""Logging filter untuk menyamarkan token atau secret pada URL, header, atau body pesan log."""

import logging
import re

_PATTERNS = [
    (re.compile(r"(access_token=)[^&\s\'\"]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(refresh_token=)[^&\s\'\"]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(client_secret=)[^&\s\'\"]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Bearer\s+)[^\s\'\"]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(OAuth\s+)[^\s\'\"]+", re.IGNORECASE), r"\1***"),
]


def mask_secrets(text: str) -> str:
    """Samarkan token atau kredensial sensitif dalam string."""
    if not isinstance(text, str):
        text = str(text)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class SecretMaskingFilter(logging.Filter):
    """Filter logging yang memformat pesan dan menyamarkan secret sebelum diteruskan ke handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            masked = mask_secrets(msg)
            record.msg = masked
            record.args = ()
        except Exception:
            pass
        return True
