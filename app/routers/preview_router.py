"""Preview endpoints."""

import threading
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.config.settings import settings
from app.core.di.dependencies import get_preview_service
from app.services.preview_service import PreviewService

router = APIRouter(prefix="/preview", tags=["preview"])

_preview_locks: dict[int, threading.Lock] = {}
_locks_mutex = threading.Lock()


def _get_candidate_lock(candidate_id: int) -> threading.Lock:
    with _locks_mutex:
        if candidate_id not in _preview_locks:
            _preview_locks[candidate_id] = threading.Lock()
        return _preview_locks[candidate_id]


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

    if not cache_path.exists() or cache_path.stat().st_size == 0:
        with _get_candidate_lock(candidate_id):
            if not cache_path.exists() or cache_path.stat().st_size == 0:
                service.build_preview_clip_file(candidate_id, str(cache_path))

    return FileResponse(cache_path, media_type="video/mp4")


@router.get("/candidates/{candidate_id}/thumbnail")
def preview_candidate_thumbnail(
    candidate_id: int,
    service: PreviewService = Depends(get_preview_service),
):
    """Serve (atau generate sekali lalu cache) thumbnail gambar (JPEG) dari full video
    untuk preview thumbnail pada candidate card.
    """
    cache_dir = settings.CACHE_DIR / "thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"candidate_{candidate_id}.jpg"

    if not cache_path.exists():
        service.build_candidate_thumbnail_file(candidate_id, str(cache_path))

    return FileResponse(cache_path, media_type="image/jpeg")


@router.get("/videos/{video_id}/thumbnail")
def preview_video_thumbnail(
    video_id: int,
    service: PreviewService = Depends(get_preview_service),
):
    """Serve (atau generate sekali lalu cache) thumbnail gambar (JPEG) dari full video
    untuk video card di halaman candidates.
    """
    cache_dir = settings.CACHE_DIR / "thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"video_{video_id}.jpg"

    if not cache_path.exists():
        service.build_video_thumbnail_file(video_id, str(cache_path))

    return FileResponse(cache_path, media_type="image/jpeg")


