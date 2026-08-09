"""Health check endpoint.

Router hanya menerima request dan memanggil Service — tidak ada
business logic maupun akses data di sini.
"""

from fastapi import APIRouter, Depends

from app.core.di.dependencies import get_health_service
from app.schemas.health_schema import HealthStatus
from app.services.health_service import HealthService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthStatus)
def get_health(service: HealthService = Depends(get_health_service)) -> HealthStatus:
    """Return the current application health status."""
    return service.check()
