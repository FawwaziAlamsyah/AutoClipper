"""Repository untuk entity InstagramPostModel."""

from sqlalchemy.orm import Session

from app.models.instagram_post_model import InstagramPostModel
from app.repositories.base_repository import PostgresRepository


class InstagramPostRepository(PostgresRepository[InstagramPostModel]):
    """Data access layer untuk riwayat dan status publikasi Instagram."""

    model_class = InstagramPostModel

    def save(self, post: InstagramPostModel) -> InstagramPostModel:
        """Simpan perubahan entity dan commit ke database."""
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)
        return post

    def get_active_for_clip(self, clip_id: int) -> InstagramPostModel | None:
        """Cari post yang sedang dalam proses aktif (mencegah klik ganda)."""
        return (
            self.db.query(InstagramPostModel)
            .filter(
                InstagramPostModel.clip_id == clip_id,
                InstagramPostModel.status.in_(["queued", "uploading", "processing"]),
            )
            .first()
        )

    def latest_for_clip(self, clip_id: int) -> InstagramPostModel | None:
        """Ambil riwayat post terbaru untuk klip tertentu."""
        return (
            self.db.query(InstagramPostModel)
            .filter(InstagramPostModel.clip_id == clip_id)
            .order_by(InstagramPostModel.id.desc())
            .first()
        )

    def list_for_clip(self, clip_id: int) -> list[InstagramPostModel]:
        """Ambil semua riwayat posting untuk klip tertentu (terbaru lebih dulu)."""
        return (
            self.db.query(InstagramPostModel)
            .filter(InstagramPostModel.clip_id == clip_id)
            .order_by(InstagramPostModel.id.desc())
            .all()
        )

    def list_stale_active(self) -> list[InstagramPostModel]:
        """Ambil semua post yang menggantung (stale) saat aplikasi restart."""
        return (
            self.db.query(InstagramPostModel)
            .filter(InstagramPostModel.status.in_(["queued", "uploading", "processing"]))
            .all()
        )
