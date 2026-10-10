"""LLM status endpoint — info sisa token/request dari last OpenAI call."""

from fastapi import APIRouter

from app.ai_modules.hook_analysis.hook_moment_finder import get_llm_status
from app.core.config.llm_config import get_active_llm
from app.core.config.settings import settings

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
def llm_status() -> dict:
    """Return status LLM terkini: sisa token, request, error terakhir."""
    status = get_llm_status()
    active = get_active_llm()
    return {
        "api_key_configured": bool(active["api_key"]),
        "api_key_set": bool(active["api_key"]),
        "use_auto_hook": settings.USE_AUTO_HOOK,
        "provider": active["provider"],
        "model": active["model"],
        **status,
    }
