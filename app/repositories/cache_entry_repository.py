"""Repository for CacheEntry model."""

from app.models.cache_entry_model import CacheEntryModel
from app.repositories.base_repository import PostgresRepository


class CacheEntryRepository(PostgresRepository[CacheEntryModel]):
    """PostgreSQL repository for cache entries."""

    model_class = CacheEntryModel

    def get_by_key(self, cache_key: str) -> CacheEntryModel | None:
        """Get a cache entry by its unique key."""
        return (
            self.db.query(CacheEntryModel)
            .filter(CacheEntryModel.cache_key == cache_key)
            .first()
        )

    def get_by_video(self, video_id: int) -> list[CacheEntryModel]:
        """Get all cache entries for a video."""
        return list(
            self.db.query(CacheEntryModel)
            .filter(CacheEntryModel.video_id == video_id)
            .all()
        )
