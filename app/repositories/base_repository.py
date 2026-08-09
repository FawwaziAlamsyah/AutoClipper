"""Generic repository interface (Repository Pattern).

Implementasi konkret (mis. untuk PostgreSQL) harus mewarisi class ini
sehingga Service tidak pernah bergantung pada detail teknis storage.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class BaseRepository(ABC, Generic[ModelType]):
    """Abstract repository defining the contract for data access."""

    @abstractmethod
    def get(self, entity_id: int) -> ModelType | None:
        """Retrieve a single entity by its ID, or None if not found."""

    @abstractmethod
    def list(self) -> list[ModelType]:
        """Retrieve all entities."""

    @abstractmethod
    def add(self, entity: ModelType) -> ModelType:
        """Persist a new entity and return it."""

    @abstractmethod
    def delete(self, entity_id: int) -> bool:
        """Delete an entity by ID. Return True if deleted."""


class PostgresRepository(BaseRepository[ModelType]):
    """Base PostgreSQL repository with common CRUD operations."""

    model_class: type[ModelType]

    def __init__(self, db: Session) -> None:
        """Initialize with a database session."""
        self.db = db

    def get(self, entity_id: int) -> ModelType | None:
        """Retrieve a single entity by its ID."""
        return self.db.get(self.model_class, entity_id)

    def list(self) -> list[ModelType]:
        """Retrieve all entities."""
        return list(self.db.query(self.model_class).all())

    def add(self, entity: ModelType) -> ModelType:
        """Persist a new entity and return it."""
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def delete(self, entity_id: int) -> bool:
        """Delete an entity by ID."""
        entity = self.get(entity_id)
        if entity is None:
            return False
        self.db.delete(entity)
        self.db.commit()
        return True
