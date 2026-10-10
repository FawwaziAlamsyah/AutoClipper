"""Persist and resolve LLM configuration (9Router vs Google Gemini).

Memungkinkan pergantian model LLM secara dinamis lewat menu Settings di UI.
Data tersimpan di data/llm_config.json agar konsisten diakses oleh
seluruh pipeline background (HookMomentFinder, LLMAnalyzer, dsb).
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

_LLM_CONFIG_FILE = Path("data/llm_config.json")

# Email akun Google pengguna dari env/settings untuk referensi UI
USER_GOOGLE_ACCOUNT = getattr(settings, "GOOGLE_ACCOUNT_EMAIL", "")

# Daftar model Gemini yang didukung
SUPPORTED_GEMINI_MODELS = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
]


def _get_defaults() -> dict[str, Any]:
    """Nilai default awal dari environment / settings."""
    env_provider = getattr(settings, "LLM_PROVIDER", "9router").lower()
    if env_provider not in ("gemini", "9router", "openai"):
        active_provider = "9router"
    elif env_provider == "gemini":
        active_provider = "gemini"
    else:
        active_provider = "9router"

    return {
        "active_provider": active_provider,
        "gemini": {
            "model": getattr(settings, "GEMINI_MODEL", "gemini-flash-latest"),
            "api_key": getattr(settings, "GEMINI_API_KEY", ""),
            "base_url": getattr(
                settings,
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ),
            "account_email": USER_GOOGLE_ACCOUNT,
        },
        "9router": {
            "model": getattr(settings, "LLM_MODEL", "DABOJI"),
            "api_key": getattr(settings, "LLM_API_KEY", ""),
            "base_url": getattr(settings, "LLM_BASE_URL", "http://localhost:20128/v1"),
        },
    }


def get_llm_config() -> dict[str, Any]:
    """Baca konfigurasi LLM dari data/llm_config.json, merge dengan defaults."""
    default = _get_defaults()
    try:
        if _LLM_CONFIG_FILE.exists():
            data = json.loads(_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
            merged = dict(default)
            if "active_provider" in data:
                merged["active_provider"] = data["active_provider"]
            if "gemini" in data and isinstance(data["gemini"], dict):
                merged["gemini"].update(data["gemini"])
            if "9router" in data and isinstance(data["9router"], dict):
                merged["9router"].update(data["9router"])

            # Auto-migrate model lama yang tidak didukung ke gemini-flash-latest
            if merged["gemini"].get("model") not in SUPPORTED_GEMINI_MODELS:
                merged["gemini"]["model"] = "gemini-flash-latest"

            return merged
    except Exception as e:
        logger.warning("Gagal membaca llm_config.json, gunakan default: %s", e)
    return default


def get_active_llm() -> dict[str, str]:
    """Ambil konfigurasi aktif untuk digunakan oleh client LLM."""
    cfg = get_llm_config()
    provider = cfg.get("active_provider", "9router")
    if provider == "gemini":
        p_cfg = cfg.get("gemini", {})
        model = p_cfg.get("model", "gemini-flash-latest")
        if model not in SUPPORTED_GEMINI_MODELS:
            model = "gemini-flash-latest"
        return {
            "provider": "gemini",
            "model": model,
            "api_key": p_cfg.get("api_key", ""),
            "base_url": p_cfg.get(
                "base_url",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ).rstrip("/"),
            "account_email": p_cfg.get("account_email", USER_GOOGLE_ACCOUNT),
        }
    else:
        p_cfg = cfg.get("9router", {})
        return {
            "provider": "9router",
            "model": p_cfg.get("model", "DABOJI"),
            "api_key": p_cfg.get("api_key", ""),
            "base_url": p_cfg.get("base_url", "http://localhost:20128/v1").rstrip("/"),
            "account_email": "",
        }


def save_llm_config(
    active_provider: str,
    gemini_model: str | None = None,
    gemini_api_key: str | None = None,
    gemini_base_url: str | None = None,
    router9_model: str | None = None,
    router9_api_key: str | None = None,
    router9_base_url: str | None = None,
) -> dict[str, Any]:
    """Simpan konfigurasi LLM ke data/llm_config.json dan sinkronkan ke runtime settings."""
    cfg = get_llm_config()
    if active_provider in ("gemini", "9router"):
        cfg["active_provider"] = active_provider

    if gemini_model:
        cfg["gemini"]["model"] = gemini_model
    if gemini_api_key is not None:
        cfg["gemini"]["api_key"] = gemini_api_key.strip()
    if gemini_base_url:
        cfg["gemini"]["base_url"] = gemini_base_url.rstrip("/")

    if router9_model:
        cfg["9router"]["model"] = router9_model
    if router9_api_key is not None:
        cfg["9router"]["api_key"] = router9_api_key.strip()
    if router9_base_url:
        cfg["9router"]["base_url"] = router9_base_url.rstrip("/")

    _LLM_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LLM_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Update in-memory settings agar konsisten
    active = get_active_llm()
    settings.LLM_PROVIDER = active["provider"]
    settings.LLM_MODEL = active["model"]
    settings.LLM_API_KEY = active["api_key"]
    settings.LLM_BASE_URL = active["base_url"]
    if active["provider"] == "gemini":
        settings.GEMINI_API_KEY = active["api_key"]
        settings.GEMINI_MODEL = active["model"]

    logger.info("LLM config disimpan: provider=%s, model=%s", active["provider"], active["model"])
    return cfg


def ping_llm_connection(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> tuple[bool, str]:
    """Uji konektivitas model dengan mengirimkan prompt singkat ke endpoint /chat/completions."""
    if not api_key or not api_key.strip():
        provider_label = "Google Gemini" if provider == "gemini" else "9Router"
        return False, f"API Key untuk {provider_label} tidak boleh kosong. Silakan masukkan API Key terlebih dahulu."

    clean_url = base_url.rstrip("/")
    start_time = time.time()
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Katakan OK."},
        ],
        "max_tokens": 10,
        "temperature": 0.1,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{clean_url}/chat/completions", headers=headers, json=payload)
            elapsed_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                body = response.json()
                reply = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or "OK"
                return True, f"Koneksi sukses! Model '{model}' merespons dalam {elapsed_ms}ms: \"{reply}\""
            elif response.status_code in (401, 403):
                return False, f"Autentikasi gagal (HTTP {response.status_code}): API Key tidak valid. Pastikan API Key benar dan akun aktif."
            elif response.status_code == 404:
                return False, f"Model '{model}' tidak tersedia (HTTP 404). Silakan pilih model 'gemini-flash-latest'."
            elif response.status_code == 503:
                # Coba uji fallback ke gemini-flash-latest jika model yang diuji bukan gemini-flash-latest
                if provider == "gemini" and model != "gemini-flash-latest":
                    fb_payload = dict(payload, model="gemini-flash-latest")
                    try:
                        fb_resp = client.post(f"{clean_url}/chat/completions", headers=headers, json=fb_payload)
                        if fb_resp.status_code == 200:
                            return True, (
                                f"Model '{model}' sedang padat trafik di Google (HTTP 503). "
                                f"Namun API Key Anda valid dan sukses terhubung via 'gemini-flash-latest'! "
                                f"Pilih model 'gemini-flash-latest' di dropdown agar proses lancar."
                            )
                    except Exception:
                        pass
                return False, f"Server Google sedang sibuk/antre (HTTP 503). Silakan pilih model 'gemini-flash-latest' yang lebih stabil."
            else:
                err_text = response.text[:200]
                return False, f"HTTP {response.status_code}: {err_text}"
    except httpx.TimeoutException:
        return False, "Request timeout setelah 30 detik. Coba lagi atau periksa koneksi internet."
    except Exception as e:
        return False, f"Gagal menghubungi server: {str(e)}"
