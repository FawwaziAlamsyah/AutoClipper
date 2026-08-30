"""OAuth, publish, & admin endpoints untuk integrasi TikTok."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.core.di.dependencies import (
    get_tiktok_account_repo,
    get_tiktok_auth_service,
    get_tiktok_upload_service,
)
from app.repositories.tiktok_account_repository import TikTokAccountRepository
from app.services.tiktok_auth_service import TikTokAuthService
from app.services.tiktok_upload_service import TikTokUploadService

router = APIRouter(prefix="/tiktok", tags=["tiktok"])


@router.get("/oauth/login")
def tiktok_oauth_login(service: TikTokAuthService = Depends(get_tiktok_auth_service)):
    """Redirect user ke halaman login+izin TikTok."""
    return RedirectResponse(service.build_authorize_url())


@router.get("/oauth/callback")
def tiktok_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    service: TikTokAuthService = Depends(get_tiktok_auth_service),
):
    """TikTok redirect ke sini setelah user login+izinkan akses."""
    account = service.handle_callback(code, state)
    return RedirectResponse(f"/upload?tiktok_connected=1&open_id={account.open_id}")


@router.get("/status")
def tiktok_connection_status(
    repo: TikTokAccountRepository = Depends(get_tiktok_account_repo),
) -> dict:
    account = repo.get_first()
    return {"connected": account is not None, "open_id": account.open_id if account else None}


@router.post("/publish/{clip_id}")
def publish_clip_to_tiktok(
    clip_id: int,
    service: TikTokUploadService = Depends(get_tiktok_upload_service),
) -> dict:
    """Mulai proses publish clip ke TikTok (mode draft/SELF_ONLY), return local_id buat polling."""
    local_id = service.start_publish(clip_id)
    return {"local_id": local_id, "status": "uploading"}


@router.get("/publish/{local_id}/status")
def get_publish_status(
    local_id: str,
    service: TikTokUploadService = Depends(get_tiktok_upload_service),
) -> dict:
    """Polling status publish dari frontend."""
    return service.get_publish_progress(local_id)