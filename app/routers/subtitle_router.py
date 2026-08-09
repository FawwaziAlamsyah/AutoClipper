"""Subtitle generation endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.subtitle_service import SubtitleService

router = APIRouter(prefix="/subtitle", tags=["subtitle"])


def _get_service(db: Session = Depends(get_db)) -> SubtitleService:
    return SubtitleService(db)


@router.post("/clips/{clip_id}", response_model=dict)
def generate_subtitle(
    clip_id: int,
    format: str = Query("srt", pattern="^(srt|vtt)$"),
    language: str = Query("id"),
    style: str = Query("minimal", pattern="^(minimal|tiktok|youtube)$"),
    service: SubtitleService = Depends(_get_service),
) -> dict:
    """Generate subtitle file for a clip with style."""
    return service.generate_subtitle(clip_id, format, language, style)
