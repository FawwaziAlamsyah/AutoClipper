"""Generate final clip endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.clip_schema import ClipGenerateRequest, ClipDetail
from app.services.clip_service import ClipService

router = APIRouter(prefix="/clips", tags=["clips"])


def _get_service(db: Session = Depends(get_db)) -> ClipService:
    return ClipService(db)


@router.post("", response_model=ClipDetail)
def generate_clip(
    req: ClipGenerateRequest,
    service: ClipService = Depends(_get_service),
) -> ClipDetail:
    """Generate a final clip from a candidate using FFmpeg."""
    clip = service.generate_clip(req.candidate_id, req.aspect_ratio, req.subtitle_enabled, req.subtitle_style)
    return ClipDetail.model_validate(clip)
