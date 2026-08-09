"""Generate final clip endpoints."""

from fastapi import APIRouter, Depends

from app.core.di.dependencies import get_clip_service
from app.schemas.clip_schema import ClipGenerateRequest, ClipDetail
from app.services.clip_service import ClipService

router = APIRouter(prefix="/clips", tags=["clips"])


@router.post("", response_model=ClipDetail)
def generate_clip(
    req: ClipGenerateRequest,
    service: ClipService = Depends(get_clip_service),
) -> ClipDetail:
    """Generate a final clip from a candidate using FFmpeg."""
    clip = service.generate_clip(req.candidate_id, req.aspect_ratio, req.subtitle_enabled, req.subtitle_style)
    return ClipDetail.model_validate(clip)
