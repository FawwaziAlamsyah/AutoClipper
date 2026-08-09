"""Dependency providers used with FastAPI's Depends().

Router tidak pernah instansiasi Service secara langsung — selalu lewat
provider di sini, agar mudah diganti dengan mock saat testing.
"""

from app.services.health_service import HealthService


def get_health_service() -> HealthService:
    """Provide a HealthService instance."""
    return HealthService()
