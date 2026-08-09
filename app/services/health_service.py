"""Health check business logic.

Service ini sengaja tidak mengenal FastAPI (Request/Response) sama
sekali, sehingga bisa dipanggil dan ditest tanpa web server.
"""

from datetime import UTC, datetime

from app.core.config.settings import settings
from app.schemas.health_schema import HealthStatus


class HealthService:
    """Provides application health information."""

    def check(self) -> HealthStatus:
        """Return the current health status of the application."""
        return HealthStatus(
            status="ok",
            app_name=settings.APP_NAME,
            environment=settings.APP_ENV,
            checked_at=datetime.now(UTC),
        )
