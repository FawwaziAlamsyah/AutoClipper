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
