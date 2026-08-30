"""Tests for i18n + theme preferences (Settings menu)."""

from fastapi.testclient import TestClient


def test_settings_page_returns_200(client: TestClient) -> None:
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Settings" in response.text


def test_default_language_is_english(client: TestClient) -> None:
    """Tanpa cookie, default bahasa English (APP_DEFAULT_LANGUAGE=en)."""
    response = client.get("/")
    assert response.status_code == 200
    assert '>Dashboard<' in response.text or "Dashboard" in response.text
    assert "data-bs-theme" in response.text


def test_switch_to_indonesian_changes_navbar(client: TestClient) -> None:
    """Simpan cookie lang=id → navbar berubah jadi Bahasa Indonesia."""
    client.post("/settings/save", data={"lang": "id", "theme": "dark"})
    response = client.get("/")
    assert response.status_code == 200
    assert 'data-bs-theme="dark"' in response.text
    assert "Beranda" in response.text  # nav.dashboard pakai bahasa Indonesia


def test_invalid_lang_falls_back_to_default(client: TestClient) -> None:
    client.post("/settings/save", data={"lang": "xx", "theme": "dark"})
    response = client.get("/")
    assert response.status_code == 200
    assert 'data-bs-theme="dark"' in response.text
    # bahasa tidak valid → default English dipakai
    assert "Dashboard" in response.text