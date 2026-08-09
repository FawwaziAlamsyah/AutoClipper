"""Subtitle generation endpoints."""

from fastapi import APIRouter, Depends, Query

from app.core.di.dependencies import get_subtitle_service
from app.services.subtitle_service import SubtitleService

router = APIRouter(prefix="/subtitle", tags=["subtitle"])


@router.post("/clips/{clip_id}", response_model=dict)
def generate_subtitle(
    clip_id: int,
    format: str = Query("srt", pattern="^(srt|vtt)$"),
    language: str = Query("id"),
    style: str = Query("minimal", pattern="^(minimal|tiktok|youtube)$"),
    service: SubtitleService = Depends(get_subtitle_service),
) -> dict:
    """Generate subtitle file for a clip with style."""
    return service.generate_subtitle(clip_id, format, language, style)
