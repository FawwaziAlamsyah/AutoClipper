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
