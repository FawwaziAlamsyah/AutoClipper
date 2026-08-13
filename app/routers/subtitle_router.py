"""Subtitle generation endpoints."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.di.dependencies import get_subtitle_service
from app.services.subtitle_service import SubtitleService

router = APIRouter(prefix="/subtitle", tags=["subtitle"])
templates = Jinja2Templates(directory="app/templates")


@router.post("/clips/{clip_id}", response_class=HTMLResponse)
def generate_subtitle(
    request: Request,
    clip_id: int,
    format: str = Form("srt"),
    language: str = Form("id"),
    style: str = Form("minimal"),
    service: SubtitleService = Depends(get_subtitle_service),
) -> HTMLResponse:
    """Generate subtitle file for a clip with style."""
    result = service.generate_subtitle(clip_id, format, language, style)
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
