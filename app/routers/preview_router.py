"""Preview endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.config.settings import settings
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


@router.get("/candidates/{candidate_id}/clip")
def preview_candidate_clip(
    candidate_id: int,
    service: PreviewService = Depends(get_preview_service),
):
    """Serve (atau generate sekali lalu cache) potongan video pendek untuk
    preview player — bukan file video mentah utuh.
    """
    cache_path = settings.CACHE_DIR / "previews" / f"candidate_{candidate_id}.mp4"

    if not cache_path.exists():
        service.build_preview_clip_file(candidate_id, str(cache_path))

    return FileResponse(cache_path, media_type="video/mp4")
