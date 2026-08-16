# Category Training 04 — CRUD Kategori (Backend)

Bagian 4 dari 14. **Prasyarat: file 01-03 sudah selesai.**

## Task — Repository

`app/repositories/category_repository.py` (file baru):

```python
"""Repository for CategoryModel."""

from sqlalchemy.orm import Session

from app.models.category_model import CategoryModel


class CategoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, category_id: int) -> CategoryModel | None:
        return self.db.query(CategoryModel).filter(CategoryModel.id == category_id).first()

    def get_all(self) -> list[CategoryModel]:
        return list(self.db.query(CategoryModel).order_by(CategoryModel.name).all())

    def get_by_name(self, name: str) -> CategoryModel | None:
        return self.db.query(CategoryModel).filter(CategoryModel.name == name).first()

    def add(self, category: CategoryModel) -> CategoryModel:
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def delete(self, category_id: int) -> None:
        category = self.get(category_id)
        if category:
            self.db.delete(category)
            self.db.commit()
```

## Task — Service

`app/services/category_service.py` (file baru):

```python
"""Business logic untuk kategori clip style."""

import logging
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions.base import NotFoundException, ValidationException
from app.models.category_model import CategoryModel
from app.repositories.category_repository import CategoryRepository

logger = logging.getLogger(__name__)


class CategoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = CategoryRepository(db)

    def list_categories(self) -> list[CategoryModel]:
        return self.repo.get_all()

    def create_category(self, name: str) -> CategoryModel:
        name = name.strip()
        if not name:
            raise ValidationException("Nama kategori tidak boleh kosong")
        if self.repo.get_by_name(name):
            raise ValidationException(f"Kategori '{name}' sudah ada")
        return self.repo.add(CategoryModel(name=name))

    def rename_category(self, category_id: int, new_name: str) -> CategoryModel:
        category = self.repo.get(category_id)
        if category is None:
            raise NotFoundException(f"Kategori {category_id} tidak ditemukan")
        new_name = new_name.strip()
        if not new_name:
            raise ValidationException("Nama kategori tidak boleh kosong")
        existing = self.repo.get_by_name(new_name)
        if existing and existing.id != category_id:
            raise ValidationException(f"Kategori '{new_name}' sudah ada")
        category.name = new_name
        self.db.commit()
        self.db.refresh(category)
        return category

    def delete_category(self, category_id: int) -> None:
        category = self.repo.get(category_id)
        if category is None:
            raise NotFoundException(f"Kategori {category_id} tidak ditemukan")
        # Hapus folder model kategori ini juga (kalau ada) — candidates/jobs
        # yang mereferensikan kategori ini TIDAK ikut terhapus (ondelete=SET NULL),
        # cuma model terlatihnya yang dibersihkan.
        model_dir = Path(f"data/models/category_{category_id}")
        if model_dir.exists():
            shutil.rmtree(model_dir)
        self.repo.delete(category_id)
        logger.info("Kategori %d dihapus beserta model terlatihnya", category_id)
```

## Task — Router

`app/routers/category_router.py` (file baru):

```python
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
```

## Task — Wiring

- Tambahkan `get_category_service` di `app/core/di/dependencies.py` (pola
  sama seperti provider lain yang sudah ada di file itu).
- Daftarkan `category_router` di `app/main.py` (pola sama seperti router
  lain yang sudah di-include).

## Definisi Selesai

- `POST /categories?name=Gaming Funny` → berhasil buat kategori baru, return
  `{"id": ..., "name": "Gaming Funny"}`.
- `POST /categories?name=Gaming Funny` (lagi, nama sama) → gagal dengan
  pesan jelas "sudah ada", bukan crash/duplikat/error 500.
- `GET /categories` → muncul kategori yang barusan dibuat.
- `PUT /categories/{id}?name=Gaming Funny Baru` → nama berubah, cek lagi
  lewat `GET /categories`.
- `DELETE /categories/{id}` → kategori hilang dari `GET /categories`.
- `pytest` tetap lulus.
- **Jangan lanjut ke file 05** sebelum poin di atas terverifikasi.
