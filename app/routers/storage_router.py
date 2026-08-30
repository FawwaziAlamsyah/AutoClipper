"""Storage dashboard endpoint."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates  # noqa: F401 (ke AppTemplates)
from app.core.jinja import AppTemplates

from app.core.config.settings import settings
from app.core.di.dependencies import get_storage_service
from app.core.htmx import render
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])
templates = AppTemplates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
def storage_dashboard(
    request: Request,
    service: StorageService = Depends(get_storage_service),
) -> HTMLResponse:
    """Halaman ringkasan penggunaan storage + daftar video yang bisa diarsipkan."""
    stats = service.get_usage_stats()
    archivable = service.get_archivable_videos()
    return render(
        request,
        templates,
        partial_name="storage_dashboard_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "stats": stats,
            "archivable": archivable,
        },
    )
