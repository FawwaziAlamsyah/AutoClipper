"""CRUD endpoints untuk kategori clip style."""

from fastapi import APIRouter, Depends

from app.core.di.dependencies import get_category_service
from app.services.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("")
def list_categories(service: CategoryService = Depends(get_category_service)) -> list[dict]:
    """List semua kategori — dipakai buat isi dropdown di Upload & Training."""
    return [{"id": c.id, "name": c.name} for c in service.list_categories()]


@router.post("")
def create_category(name: str, service: CategoryService = Depends(get_category_service)) -> dict:
    category = service.create_category(name)
    return {"id": category.id, "name": category.name}


@router.put("/{category_id}")
def rename_category(
    category_id: int, name: str, service: CategoryService = Depends(get_category_service)
) -> dict:
    category = service.rename_category(category_id, name)
    return {"id": category.id, "name": category.name}


@router.delete("/{category_id}")
def delete_category(category_id: int, service: CategoryService = Depends(get_category_service)) -> dict:
    service.delete_category(category_id)
    return {"detail": "Kategori dihapus"}
