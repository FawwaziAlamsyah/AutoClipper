"""Repository for CacheEntry model."""

from app.models.cache_entry_model import CacheEntry
from app.repositories.base_repository import PostgresRepository


class CacheEntryRepository(PostgresRepository[CacheEntry]):
    """PostgreSQL repository for cache entries."""

    model_class = CacheEntry

    def get_by_key(self, cache_key: str) -> CacheEntry | None:
        """Get a cache entry by its unique key."""
        return (
            self.db.query(CacheEntry)
            .filter(CacheEntry.cache_key == cache_key)
            .first()
        )

    def get_by_video(self, video_id: int) -> list[CacheEntry]:
        """Get all cache entries for a video."""
        return list(
            self.db.query(CacheEntry)
            .filter(CacheEntry.video_id == video_id)
            .all()
        )
