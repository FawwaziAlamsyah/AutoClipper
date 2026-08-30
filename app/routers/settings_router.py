"""Settings menu: bahasa + tema UI.

GET  /settings         → render halaman preferences.
POST /settings/save    → simpan ke cookie, redirect balik.

State disimpan di cookie `daboclip_pref` (JSON) — dibaca ulang tiap request
oleh AppTemplates (app/core/jinja.py). Tanpa DB, tanpa user account.
"""

import json

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import RedirectResponse

from app.core.config.settings import settings
from app.core.jinja import PREF_COOKIE, AppTemplates

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
def settings_page(request: Request):
    """Halaman preferences — full page (bukan partial htmx)."""
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
        },
    )


@router.post("/save")
def settings_save(
    request: Request,
    lang: str = Form("en"),
    theme: str = Form("light"),
):
    """Simpan preferensi ke cookie, kembali ke halaman sebelumnya."""
    if lang not in ("en", "id"):
        lang = settings.APP_DEFAULT_LANGUAGE
    if theme not in ("light", "dark"):
        theme = settings.APP_DEFAULT_THEME

    resp = RedirectResponse(url=request.headers.get("referer") or "/", status_code=303)
    resp.set_cookie(**_cookie({"lang": lang, "theme": theme}))
    return resp