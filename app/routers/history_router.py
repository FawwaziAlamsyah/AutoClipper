"""History endpoints."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.db.session import get_db
from app.schemas.history_schema import HistoryDetail
from app.services.history_service import HistoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["history"])
templates = Jinja2Templates(directory="app/templates")


def _get_service(db: Session = Depends(get_db)) -> HistoryService:
    return HistoryService(db)


@router.get("", response_class=HTMLResponse)
def history_page(request: Request, service: HistoryService = Depends(_get_service)) -> HTMLResponse:
    """Render the history page."""
    entries = service.list_all()
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "app_name": settings.APP_NAME,
            "entries": entries,
        },
    )


@router.get("/api", response_model=list[HistoryDetail])
def list_history(service: HistoryService = Depends(_get_service)) -> list[HistoryDetail]:
    """List recent history entries (JSON API)."""
    return [HistoryDetail.model_validate(h) for h in service.list_all()]
