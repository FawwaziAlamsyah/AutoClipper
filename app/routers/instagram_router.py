"""Router API untuk integrasi Instagram Reels."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.di.dependencies import (
    get_db,
    get_instagram_post_service,
    get_instagram_publish_service,
)
from app.services.instagram_post_service import InstagramPostService
from app.services.instagram_publish_service import InstagramPublishService
from app.services.token_manager.setup import build_default_manager

router = APIRouter(prefix="/instagram", tags=["instagram"])


class InstagramPublishRequest(BaseModel):
    caption: str = ""
    share_to_feed: bool = True
    confirm_repost: bool = False
    fit_mode: Literal["pad", "blur", "off"] | None = None


@router.get("/status")
def get_instagram_status(db: Session = Depends(get_db)) -> dict:
    """Ambil ringkasan status integrasi token akun Instagram (tanpa secret)."""
    manager = build_default_manager()
    tokens = manager.get_status(db)
    ig_token = next((t for t in tokens if t["platform"] == "instagram"), None)

    configured = bool(settings.IG_ACCESS_TOKEN and settings.IG_USER_ID)
    connected = ig_token is not None and ig_token.get("status") == "active"
    status = ig_token.get("status") if ig_token else ("not_configured" if not configured else "needs_reconnect")
    expires_at = (
        ig_token["expires_at"].isoformat()
        if ig_token and ig_token.get("expires_at")
        else None
    )
    days_left = (
        int(ig_token["days_left"])
        if ig_token and ig_token.get("days_left") is not None
        else None
    )
    last_error = ig_token.get("last_error") if ig_token else None
    username = ig_token.get("account_id") if ig_token else (settings.IG_USER_ID or None)

    return {
        "configured": configured,
        "connected": connected,
        "status": status,
        "username": username,
        "expires_at": expires_at,
        "days_left": days_left,
        "last_error": last_error,
    }


@router.post("/publish/{clip_id}")
def publish_instagram_reel(
    clip_id: int,
    body: InstagramPublishRequest,
    post_service: InstagramPostService = Depends(get_instagram_post_service),
) -> dict:
    """Mulai proses upload & publish klip ke Instagram Reels di background thread."""
    local_id = post_service.start_publish(
        clip_id=clip_id,
        caption=body.caption,
        share_to_feed=body.share_to_feed,
        confirm_repost=body.confirm_repost,
        fit_mode=body.fit_mode,
    )
    return {"local_id": local_id, "status": "uploading"}


@router.get("/publish/{local_id}/status")
def get_publish_status(
    local_id: str,
    post_service: InstagramPostService = Depends(get_instagram_post_service),
) -> dict:
    """Ambil status dan progres penerbitan Reels saat ini."""
    return post_service.get_progress(local_id)


@router.get("/preflight/{clip_id}")
def get_preflight_status(
    clip_id: int,
    caption: str = Query("", description="Caption yang akan divalidasi"),
    fit_mode: str | None = Query(None, description="Mode reframing: pad, blur, off"),
    publish_service: InstagramPublishService = Depends(get_instagram_publish_service),
) -> dict:
    """Jalankan preflight check untuk klip tertentu sebelum user memposting."""
    report = publish_service.preflight(clip_id=clip_id, caption=caption, fit_mode=fit_mode)
    return {
        "ok": report.ok,
        "errors": report.errors,
        "warnings": report.warnings,
        "duration_seconds": report.duration_seconds,
        "will_reframe": report.will_reframe,
        "fit_mode": report.fit_mode,
    }


@router.get("/posts/{clip_id}")
def get_clip_posts(
    clip_id: int,
    post_service: InstagramPostService = Depends(get_instagram_post_service),
) -> list[dict]:
    """Ambil riwayat publikasi Instagram untuk klip tertentu (terbaru lebih dulu)."""
    posts = post_service.list_posts_for_clip(clip_id)
    return [
        {
            "id": p.id,
            "status": p.status,
            "permalink": p.permalink,
            "error_message": p.error_message,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "published_at": p.published_at.isoformat() if p.published_at else None,
        }
        for p in posts
    ]
