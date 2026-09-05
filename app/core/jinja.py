"""Jinja2Templates subclass yang menyuntik preferences UI ke semua render.

Semua halaman di-render lewat instance subclass ini → otomatis dapat:
- `t`: fungsi translate(key) sesuai bahasa user (dari cookie / default).
- `current_lang`: "en" | "id"
- `theme`: "light" | "dark"

Tidak ada template yang perlu inject manual — satu tempat, tidak ada yang terlewat.
"""

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.translate import TRANSLATIONS, make_translator

PREF_COOKIE = "daboclip_pref"  # JSON: {"lang":"en","theme":"light"}


def parse_pref(request: Request) -> tuple[str, str]:
    """Baca cookie preferences → (lang, theme). Invalid → default settings."""
    try:
        import json

        pref = json.loads(request.cookies.get(PREF_COOKIE) or "{}")
    except (ValueError, TypeError):
        pref = {}
    lang = pref.get("lang") or settings.APP_DEFAULT_LANGUAGE
    theme = pref.get("theme") or settings.APP_DEFAULT_THEME
    if lang not in ("en", "id"):
        lang = settings.APP_DEFAULT_LANGUAGE
    if theme not in ("light", "dark"):
        theme = settings.APP_DEFAULT_THEME
    return lang, theme


def _cachebust(path: str) -> str:
    """Query string cache-bust dari mtime file (detik).

    Pakai di URL media local: `_clip_edit_preview.html` → `?v=<mtime>`.
    Lebih andal dari `int(time.time())` (ts sama utk render <1 detik → browser
    cache file lama yang sudah berubah isinya, mis. hook di-regenerate).
    """
    try:
        return str(int(__import__("os").path.getmtime(path)))
    except OSError:
        return str(int(__import__("time").time()))


class AppTemplates(Jinja2Templates):
    """Jinja2Templates + inject `t`, `current_lang`, `theme` ke tiap context."""

    def __init__(self, directory: str = "app/templates"):
        super().__init__(directory=directory)
        self.env.globals["cachebust"] = _cachebust

    def TemplateResponse(self, request: Request, name: str, context: dict | None = None, **kwargs):
        lang, theme = parse_pref(request)
        ctx = dict(context or {})
        ctx.setdefault("t", make_translator(lang))
        ctx.setdefault("current_lang", lang)
        ctx.setdefault("theme", theme)
        # Kamus lengkap bahasa aktif utk dipakai JS (`__t` di base.html).
        ctx.setdefault("t_js", dict(TRANSLATIONS[lang]) if lang in TRANSLATIONS else TRANSLATIONS["en"])
        return super().TemplateResponse(request=request, name=name, context=ctx, **kwargs)