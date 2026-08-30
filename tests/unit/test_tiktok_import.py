"""Tests untuk import token TikTok manual (skip OAuth) & roundtrip enkripsi."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions.base import ValidationException
from app.core.security.token_crypto import decrypt_token
from app.repositories.tiktok_account_repository import TikTokAccountRepository
from app.services.tiktok_auth_service import TikTokAuthService


def test_import_token_roundtrip(db_session: Session) -> None:
    service = TikTokAuthService(db_session)
    open_id = f"open-id-{uuid.uuid4().hex}"
    account = service.import_token(
        access_token="test-access-token-123",
        open_id=open_id,
        expires_in=36000,
    )

    assert account.open_id == open_id
    assert decrypt_token(account.access_token_encrypted) == "test-access-token-123"

    saved = TikTokAccountRepository(db_session).get_by_open_id(open_id)
    assert saved is not None
    assert decrypt_token(saved.access_token_encrypted) == "test-access-token-123"


def test_import_token_empty_rejected(db_session: Session) -> None:
    service = TikTokAuthService(db_session)
    with pytest.raises(ValidationException, match="wajib diisi"):
        service.import_token(access_token="")


def test_import_router_endpoint(client: TestClient) -> None:
    from app.db.session import SessionLocal
    from app.models.tiktok_account_model import TikTokAccountModel

    open_id = f"open-id-router-{uuid.uuid4().hex}"
    resp = client.post(
        "/tiktok/admin/import",
        json={"access_token": "router-test-token", "open_id": open_id, "expires_in": 36000},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["open_id"] == open_id

    # Cleanup row yang dibuat via client (pakai session terpisah, bukan rollback fixture)
    db = SessionLocal()
    try:
        acc = db.query(TikTokAccountModel).filter(TikTokAccountModel.open_id == open_id).first()
        if acc:
            db.delete(acc)
            db.commit()
    finally:
        db.close()