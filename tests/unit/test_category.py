"""Unit tests for category repository, service, and router."""

import pytest
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

