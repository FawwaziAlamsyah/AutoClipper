"""Tests for legal pages (Privacy Policy & Terms of Service)."""

from fastapi.testclient import TestClient


def test_privacy_policy_returns_200(client: TestClient) -> None:
    response = client.get("/privacy-policy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text


def test_terms_of_service_returns_200(client: TestClient) -> None:
    response = client.get("/terms-of-service")
    assert response.status_code == 200
    assert "Terms of Service" in response.text