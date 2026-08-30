"""History endpoints."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates  # noqa: F401 (ke AppTemplates)
from app.core.jinja import AppTemplates

from app.core.config.settings import settings
from app.core.di.dependencies import get_history_service
from app.core.htmx import render
from app.schemas.history_schema import HistoryDetail
from app.services.history_service import HistoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["history"])
templates = AppTemplates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def history_page(request: Request, service: HistoryService = Depends(get_history_service)) -> HTMLResponse:
    """Render the history page."""
    entries = service.list_all()
    return render(
        request,
        templates,
        partial_name="history_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "entries": entries,
        },
    )


@router.get("/api", response_model=list[HistoryDetail])
def list_history(service: HistoryService = Depends(get_history_service)) -> list[HistoryDetail]:
    """List recent history entries (JSON API)."""
    return [HistoryDetail.model_validate(h) for h in service.list_all()]
