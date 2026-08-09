"""Application exception hierarchy.

Semua exception domain diturunkan dari AppException agar bisa ditangani
secara seragam oleh global exception handler (lihat handlers.py).
"""


class AppException(Exception):
    """Base class for all application-specific exceptions."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        """Initialize with a human-readable message and HTTP status code."""
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundException(AppException):
    """Raised when a requested resource does not exist."""

    def __init__(self, message: str = "Resource not found") -> None:
        """Initialize with a 404 status code."""
        super().__init__(message, status_code=404)


class ValidationException(AppException):
    """Raised when input data fails a domain validation rule."""

    def __init__(self, message: str = "Invalid data") -> None:
        """Initialize with a 422 status code."""
        super().__init__(message, status_code=422)


class ExternalToolException(AppException):
    """Raised when an external tool (FFmpeg, Whisper, etc.) fails."""

    def __init__(self, message: str = "External tool error") -> None:
        """Initialize with a 500 status code."""
        super().__init__(message, status_code=500)
