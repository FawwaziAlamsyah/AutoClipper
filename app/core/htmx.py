"""Helper render dual-mode: partial (htmx) vs full page (navigasi langsung)."""

from fastapi import Request
from fastapi.templating import Jinja2Templates


def render(
    request: Request,
    templates: Jinja2Templates,
    partial_name: str,
    context: dict,
    full_name: str = "base.html",
):
    """Render partial template kalau request dari htmx, full page kalau tidak.

    partial_name: template isi konten SAJA (tanpa {% extends %}).
    full_name: template pembungkus (default base.html) yang include partial_name.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return templates.TemplateResponse(request=request, name=partial_name, context=context)
    context["_content_partial"] = partial_name
    return templates.TemplateResponse(request=request, name=full_name, context=context)

