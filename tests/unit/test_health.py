"""Tests for the health endpoint."""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """GET /health should return HTTP 200 with status 'ok'."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_index_page_loads(client: TestClient) -> None:
    """GET / should render the landing page successfully."""
    response = client.get("/")

    assert response.status_code == 200
