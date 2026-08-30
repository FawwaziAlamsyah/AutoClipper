"""OAuth, publish, & admin endpoints untuk integrasi TikTok."""

from fastapi import APIRouter, Body, Depends, Query
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


@router.get("/oauth/debug-url")
def tiktok_oauth_debug_url(service: TikTokAuthService = Depends(get_tiktok_auth_service)) -> dict:
    """DEBUG: return raw authorize URL biar bisa diinspeksi manual di browser."""
    return {"url": service.build_authorize_url()}


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


@router.post("/admin/import")
def tiktok_admin_import(
    access_token: str = Body(...),
    open_id: str | None = Body(default=None),
    refresh_token: str = Body(default=""),
    expires_in: int | None = Body(default=None),
    service: TikTokAuthService = Depends(get_tiktok_auth_service),
) -> dict:
    """Import token manual (sandbox/test) langsung ke DB — skip OAuth.

    Dipakai karena sandbox TikTok menolak PKCE exchange (tiktok02.md). Kalau
    open_id tidak dikirim, coba ambil otomatis lewat user info.
    """
    account = service.import_token(access_token, open_id, refresh_token, expires_in)
    return {"connected": True, "open_id": account.open_id, "expires_at": account.expires_at.isoformat()}


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