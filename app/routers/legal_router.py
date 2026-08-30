"""Legal pages: Privacy Policy & Terms of Service.

Halaman statis full-page (extends base.html), bukan partial htmx — dikunjungi
langsung dari breadcrumb/footer, bukan lewat navigasi swap.

Route hanya render template — tidak ada business logic / akses data.
"""

from datetime import date

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates  # noqa: F401 (ke AppTemplates)
from app.core.jinja import AppTemplates

from app.core.config.settings import settings

router = APIRouter(tags=["legal"])

templates = AppTemplates(directory="app/templates")

# Last Updated di-hitung dari perubahan terakhir halaman ini — update manual
# tiap kali isi legal berubah. Format ISO (YYYY-MM-DD) agar mudah dibaca.
LAST_UPDATED = date(2026, 8, 29)


def _context(request: Request) -> dict:
    """Context bersama kedua halaman legal."""
    return {
        "request": request,
        "app_name": settings.APP_NAME,
        "contact_email": settings.APP_CONTACT_EMAIL,
        "last_updated": LAST_UPDATED.isoformat(),
        # Base URL publik halaman legal (bisa overridden via APP_PUBLIC_URL).
        "legal_base_url": settings.APP_PUBLIC_URL or str(request.base_url).rstrip("/"),
    }


@router.get("/privacy-policy")
def privacy_policy(request: Request):
    """Privacy Policy — halaman full page."""
    return templates.TemplateResponse(
        request=request, name="privacy_policy.html", context=_context(request)
    )


@router.get("/terms-of-service")
def terms_of_service(request: Request):
    """Terms of Service — halaman full page."""
    return templates.TemplateResponse(
        request=request, name="terms_of_service.html", context=_context(request)
    )