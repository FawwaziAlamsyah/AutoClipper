"""Subtitle generation endpoints."""

import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates  # noqa: F401 (ke AppTemplates)
from sqlalchemy.orm import Session
from app.core.jinja import AppTemplates

from app.core.di.dependencies import get_subtitle_service
from app.db.session import get_db
from app.repositories.clip_repository import ClipRepository
from app.services.subtitle_service import SubtitleService

router = APIRouter(prefix="/subtitle", tags=["subtitle"])
templates = AppTemplates(directory="app/templates")


@router.post("/clips/{clip_id}", response_class=HTMLResponse)
def generate_subtitle(
    request: Request,
    clip_id: int,
    format: str = Form("srt"),
    language: str = Form("id"),
    style: str = Form("minimal"),
    burn: bool = Form(True),
    db: Session = Depends(get_db),
    service: SubtitleService = Depends(get_subtitle_service),
) -> HTMLResponse:
    """Generate subtitle — burn langsung ke klip (default) atau cuma file SRT/VTT."""
    from fastapi import HTTPException

    try:
        result = service.generate_subtitle(clip_id, format, language, style, burn=burn)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if result["burned"]:
        # Refresh video preview biar subtitle baru keliatan nempel.
        clip = ClipRepository(db).get(clip_id)
        return templates.TemplateResponse(
            request=request,
            name="_clip_edit_preview.html",
            context={"request": request, "clip": clip, "ts": int(time.time())},
        )

    return templates.TemplateResponse(
        request=request,
        name="_subtitle_result.html",
        context={
            "request": request,
            "content": result["content"],
            "file_path": result["file_path"],
            "format": result["format"]
        }
    )
