"""Tests for LLM configuration, provider selection (9Router vs Gemini), and settings integration."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config.llm_config import (
    get_llm_config,
    get_active_llm,
    save_llm_config,
    ping_llm_connection,
    _LLM_CONFIG_FILE,
)
from app.core.config.settings import settings


def test_default_llm_config() -> None:
    """Konfigurasi default memiliki 9router dan gemini dengan struktur lengkap."""
    cfg = get_llm_config()
    assert "active_provider" in cfg
    assert "gemini" in cfg
    assert "9router" in cfg
    assert "model" in cfg["gemini"]
    assert "base_url" in cfg["gemini"]
    assert "model" in cfg["9router"]


def test_save_and_switch_to_gemini(tmp_path: Path) -> None:
    """Menyimpan provider gemini mengupdate active provider dan in-memory settings."""
    test_file = tmp_path / "llm_config.json"
    with patch("app.core.config.llm_config._LLM_CONFIG_FILE", test_file):
        save_llm_config(
            active_provider="gemini",
            gemini_model="gemini-3.8-flash",
            gemini_api_key="dummy-gemini-key-123",
        )

        active = get_active_llm()
        assert active["provider"] == "gemini"
        assert active["model"] == "gemini-3.8-flash"
        assert active["api_key"] == "dummy-gemini-key-123"
        assert "generativelanguage.googleapis.com" in active["base_url"]
        assert "account_email" in active

        # Sinkronisasi runtime settings
        assert settings.LLM_PROVIDER == "gemini"
        assert settings.LLM_MODEL == "gemini-3.8-flash"
        assert settings.LLM_API_KEY == "dummy-gemini-key-123"


def test_save_and_switch_to_9router(tmp_path: Path) -> None:
    """Menyimpan provider 9router mengupdate active provider."""
    test_file = tmp_path / "llm_config.json"
    with patch("app.core.config.llm_config._LLM_CONFIG_FILE", test_file):
        save_llm_config(
            active_provider="9router",
            router9_model="DABOJI-CUSTOM",
            router9_base_url="http://localhost:20128/v1",
            router9_api_key="dummy-router9-key-456",
        )

        active = get_active_llm()
        assert active["provider"] == "9router"
        assert active["model"] == "DABOJI-CUSTOM"
        assert active["api_key"] == "dummy-router9-key-456"
        assert settings.LLM_PROVIDER == "9router"
        assert settings.LLM_MODEL == "DABOJI-CUSTOM"


def test_check_llm_connection_empty_key() -> None:
    """Jika API key kosong, ping_llm_connection mengembalikan False dengan pesan jelas."""
    ok, msg = ping_llm_connection("gemini", "gemini-3.8-flash", "", "https://example.com")
    assert ok is False
    assert "kosong" in msg.lower()


def test_check_llm_connection_success() -> None:
    """Mock test koneksi berhasil ketika status code 200."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "OK"}}]
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        ok, msg = ping_llm_connection("gemini", "gemini-3.8-flash", "test-key", "https://example.com")
        assert ok is True
        assert "sukses" in msg.lower() or "berhasil" in msg.lower()

