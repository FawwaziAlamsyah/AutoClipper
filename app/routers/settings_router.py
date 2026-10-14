"""Settings menu: bahasa + tema UI.

GET  /settings         → render halaman preferences.
POST /settings/save    → simpan ke cookie, redirect balik.

State disimpan di cookie `daboclip_pref` (JSON) — dibaca ulang tiap request
oleh AppTemplates (app/core/jinja.py). Tanpa DB, tanpa user account.
"""

import json

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.config.score_blend import get_blend, save_blend
from app.core.config.llm_config import (
    get_llm_config,
    save_llm_config,
    ping_llm_connection,
    SUPPORTED_GEMINI_MODELS,
    USER_GOOGLE_ACCOUNT,
)
from app.core.di.dependencies import get_db
from app.core.jinja import PREF_COOKIE, AppTemplates
from app.repositories.tiktok_account_repository import TikTokAccountRepository
from app.services.token_manager.setup import build_default_manager

router = APIRouter(prefix="/settings", tags=["settings"])

templates = AppTemplates(directory="app/templates")


def _cookie(pref: dict) -> dict:
    """Pengaturan cookie preferences: httpOnly (aman dari XSS), path / agar
    berlaku di seluruh halaman."""
    return {
        "key": PREF_COOKIE,
        "value": json.dumps(pref),
        "path": "/",
        "max_age": 31536000,  # 1 tahun
        "secure": False,
        "httponly": True,
        "samesite": "lax",
    }


@router.get("")
def settings_page(request: Request, db: Session = Depends(get_db)):
    """Halaman preferences — full page (bukan partial htmx)."""
    blend = get_blend()
    llm_cfg = get_llm_config()

    # TikTok status
    tiktok_repo = TikTokAccountRepository(db)
    tiktok_account = tiktok_repo.get_first()
    tiktok_status = {
        "connected": tiktok_account is not None,
        "open_id": tiktok_account.open_id if tiktok_account else None,
        "expires_at": tiktok_account.expires_at.strftime("%Y-%m-%d %H:%M UTC") if tiktok_account and tiktok_account.expires_at else None,
    }

    # Instagram status
    manager = build_default_manager()
    tokens = manager.get_status(db)
    ig_token = next((t for t in tokens if t["platform"] == "instagram"), None)
    configured = bool(settings.IG_ACCESS_TOKEN and settings.IG_USER_ID)
    ig_status = {
        "configured": configured,
        "connected": ig_token is not None and ig_token.get("status") == "active",
        "status": ig_token.get("status") if ig_token else ("not_configured" if not configured else "needs_reconnect"),
        "username": ig_token.get("account_id") if ig_token else (settings.IG_USER_ID or None),
        "days_left": int(ig_token["days_left"]) if ig_token and ig_token.get("days_left") is not None else None,
    }

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "trained_weight": blend["trained_weight"],
            "fallback_weight": blend["fallback_weight"],
            "llm_config": llm_cfg,
            "gemini_models": SUPPORTED_GEMINI_MODELS,
            "user_google_account": USER_GOOGLE_ACCOUNT,
            "tiktok_status": tiktok_status,
            "ig_status": ig_status,
        },
    )


@router.post("/save")
def settings_save(
    request: Request,
    lang: str = Form("en"),
    theme: str = Form("light"),
    trained_weight: float = Form(0.8),
    fallback_weight: float = Form(0.2),
    # LLM Settings (opsional bila form dikirim parsial atau dari modul lain)
    llm_provider: str | None = Form(None),
    gemini_model: str = Form("gemini-flash-latest"),
    gemini_api_key: str | None = Form(None),
    router9_model: str | None = Form(None),
    router9_base_url: str | None = Form(None),
    router9_api_key: str | None = Form(None),
):
    """Simpan preferensi UI, rasio skor blend, dan model LLM aktif."""
    if lang not in ("en", "id"):
        lang = settings.APP_DEFAULT_LANGUAGE
    if theme not in ("light", "dark"):
        theme = settings.APP_DEFAULT_THEME

    save_blend(trained_weight, fallback_weight)

    if llm_provider is not None:
        save_llm_config(
            active_provider=llm_provider,
            gemini_model=gemini_model,
            gemini_api_key=gemini_api_key,
            router9_model=router9_model,
            router9_base_url=router9_base_url,
            router9_api_key=router9_api_key,
        )

    resp = RedirectResponse(url=request.headers.get("referer") or "/", status_code=303)
    resp.set_cookie(**_cookie({"lang": "en", "theme": "dark"}))
    return resp


@router.post("/test-llm")
def settings_test_llm(
    llm_provider: str = Form("9router"),
    gemini_model: str = Form("gemini-flash-latest"),
    gemini_api_key: str = Form(""),
    router9_model: str = Form("DABOJI"),
    router9_base_url: str = Form("http://localhost:20128/v1"),
    router9_api_key: str = Form(""),
):
    """Endpoint HTMX untuk menguji konektivitas model LLM secara real-time."""
    if llm_provider == "gemini":
        ok, msg = ping_llm_connection(
            provider="gemini",
            model=gemini_model,
            api_key=gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )
    else:
        ok, msg = ping_llm_connection(
            provider="9router",
            model=router9_model,
            api_key=router9_api_key,
            base_url=router9_base_url,
        )

    alert_class = "alert-success" if ok else "alert-danger"
    icon = "✓" if ok else "✗"
    return HTMLResponse(
        f'<div class="alert {alert_class} py-2 px-3 small mt-2 mb-0" role="alert">'
        f'<strong>{icon}</strong> {msg}'
        f'</div>'
    )