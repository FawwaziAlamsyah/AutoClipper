"""Unit tests for category repository, service, and router."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions.base import NotFoundException, ValidationException
from app.models.category_model import CategoryModel
from app.repositories.category_repository import CategoryRepository
from app.services.category_service import CategoryService


def test_category_repository_crud(db_session: Session) -> None:
    repo = CategoryRepository(db_session)

    # Add
    cat = repo.add(CategoryModel(name="Repo Test Cat"))
    assert cat.id is not None
    assert cat.name == "Repo Test Cat"

    # Get & Get by name
    assert repo.get(cat.id) == cat
    assert repo.get_by_name("Repo Test Cat") == cat

    # Get all
    all_cats = repo.get_all()
    assert any(c.id == cat.id for c in all_cats)

    # Delete
    repo.delete(cat.id)
    assert repo.get(cat.id) is None


def test_category_service_crud_and_validation(db_session: Session) -> None:
    service = CategoryService(db_session)

    # Create
    cat = service.create_category("  Gaming Funny  ")
    assert cat.name == "Gaming Funny"

    # Create Duplicate -> ValidationException
    with pytest.raises(ValidationException, match="sudah ada"):
        service.create_category("Gaming Funny")

    # Create Empty -> ValidationException
    with pytest.raises(ValidationException, match="tidak boleh kosong"):
        service.create_category("   ")

    # Rename
    renamed = service.rename_category(cat.id, " Gaming Funny Baru ")
    assert renamed.name == "Gaming Funny Baru"

    # Rename Nonexistent -> NotFoundException
    with pytest.raises(NotFoundException):
        service.rename_category(999999, "Baru")

    # Delete
    service.delete_category(cat.id)

    # Delete Nonexistent -> NotFoundException
    with pytest.raises(NotFoundException):
        service.delete_category(cat.id)


def test_category_router_endpoints(client: TestClient) -> None:
    # 1. POST /categories?name=Gaming Funny
    resp = client.post("/categories", params={"name": "Gaming Funny"})
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["name"] == "Gaming Funny"
    cat_id = data["id"]

    # 2. POST duplicate /categories?name=Gaming Funny -> 422 ValidationException
    resp_dup = client.post("/categories", params={"name": "Gaming Funny"})
    assert resp_dup.status_code == 422
    assert "sudah ada" in resp_dup.json()["detail"]

    # 3. GET /categories
    resp_get = client.get("/categories")
    assert resp_get.status_code == 200
    categories = resp_get.json()
    assert any(c["id"] == cat_id and c["name"] == "Gaming Funny" for c in categories)

    # 4. PUT /categories/{id}?name=Gaming Funny Baru
    resp_put = client.put(f"/categories/{cat_id}", params={"name": "Gaming Funny Baru"})
    assert resp_put.status_code == 200
    assert resp_put.json()["name"] == "Gaming Funny Baru"

    # Verify update via GET
    resp_get_updated = client.get("/categories")
    assert any(c["id"] == cat_id and c["name"] == "Gaming Funny Baru" for c in resp_get_updated.json())

    # 5. DELETE /categories/{id}
    resp_del = client.delete(f"/categories/{cat_id}")
    assert resp_del.status_code == 200
    assert resp_del.json()["detail"] == "Kategori dihapus"

    # Verify deleted via GET
    resp_get_final = client.get("/categories")
    assert not any(c["id"] == cat_id for c in resp_get_final.json())
