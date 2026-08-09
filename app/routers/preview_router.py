"""Preview endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.preview_service import PreviewService

router = APIRouter(prefix="/preview", tags=["preview"])


def _get_service(db: Session = Depends(get_db)) -> PreviewService:
    return PreviewService(db)


@router.get("/candidates/{candidate_id}")
def preview_candidate(
    candidate_id: int,
    service: PreviewService = Depends(_get_service),
) -> dict:
    """Return preview payload for a candidate clip."""
    return service.get_candidate_preview(candidate_id)
