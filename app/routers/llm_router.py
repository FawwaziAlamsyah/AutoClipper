"""LLM status endpoint — info sisa token/request dari last OpenAI call."""

from fastapi import APIRouter

from app.ai_modules.hook_analysis.hook_moment_finder import get_llm_status
from app.core.config.settings import settings

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
def llm_status() -> dict:
    """Return status LLM terkini: sisa token, request, error terakhir.

    Data diambil dari header response OpenAI terakhir (in-memory cache).
    None = belum pernah ada LLM call sejak server start.
    """
    status = get_llm_status()
    return {
        "api_key_configured": bool(settings.LLM_API_KEY),
        "use_auto_hook": settings.USE_AUTO_HOOK,
        "model": settings.LLM_MODEL,
        **status,
    }
