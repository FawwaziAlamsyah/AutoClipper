"""Preview endpoints."""

from fastapi import APIRouter, Depends

from app.core.di.dependencies import get_preview_service
from app.services.preview_service import PreviewService

router = APIRouter(prefix="/preview", tags=["preview"])


@router.get("/candidates/{candidate_id}")
def preview_candidate(
    candidate_id: int,
    service: PreviewService = Depends(get_preview_service),
) -> dict:
    """Return preview payload for a candidate clip."""
    return service.get_candidate_preview(candidate_id)
