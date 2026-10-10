"""Orkestrasi publikasi Instagram Reels di background thread dan pelacakan riwayat."""

from datetime import datetime, timezone
import logging
import threading
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions.base import ValidationException
from app.models.instagram_post_model import InstagramPostModel
from app.repositories.clip_repository import ClipRepository
from app.repositories.instagram_post_repository import InstagramPostRepository
from app.services.instagram_publish_service import (
    InstagramPublishService,
    PublishUncertainError,
)
from app.services.token_manager.manager import TokenManager
from app.services.token_manager.setup import build_default_manager

logger = logging.getLogger(__name__)

# Progress publish aktif — in-memory dictionary (pola sama seperti _TIKTOK_PUBLISHES)
_IG_PUBLISHES: dict[str, dict] = {}


class InstagramPostService:
    """Service untuk menangani posting Instagram di background dan status progres."""

    def __init__(
        self,
        db: Session,
        publish_service: InstagramPublishService | None = None,
        token_manager: TokenManager | None = None,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.db = db
        self.token_manager = token_manager or build_default_manager()
        self.clip_repo = ClipRepository(db)
        self.post_repo = InstagramPostRepository(db)
        self.publish_service = publish_service or InstagramPublishService(db, token_manager=self.token_manager)
        self.session_factory = session_factory

    def start_publish(
        self,
        clip_id: int,
        caption: str,
        share_to_feed: bool = True,
        confirm_repost: bool = False,
        fit_mode: str | None = None,
    ) -> str:
        """Jalankan preflight sinkron dan mulai publish di background daemon thread."""
        # 1. Cek apakah ada proses publish yang sedang berjalan untuk klip ini
        active = self.post_repo.get_active_for_clip(clip_id)
        if active:
            raise ValidationException("Klip ini sedang dalam proses publikasi ke Instagram.")

        # 2. Cek keberadaan clip dan status repost
        clip = self.clip_repo.get(clip_id)
        if not clip:
            raise ValidationException(f"Klip dengan ID {clip_id} tidak ditemukan.")

        if clip.instagram_published and not confirm_repost:
            raise ValidationException("Klip ini sudah pernah dikirim ke Instagram. Berikan konfirmasi untuk repost.")

        # 3. Jalankan preflight secara SINKRON agar error validasi langsung kembali ke caller (HTTP 422)
        report = self.publish_service.preflight(clip_id, caption, fit_mode=fit_mode)
        if not report.ok:
            raise ValidationException("; ".join(report.errors))

        # 4. Buat baris riwayat posting awal di database
        post = InstagramPostModel(
            clip_id=clip_id,
            caption=caption,
            share_to_feed=share_to_feed,
            status="uploading",
        )
        post = self.post_repo.save(post)

        # 5. Inisialisasi in-memory tracking
        local_id = f"ig_{uuid.uuid4().hex[:8]}"
        _IG_PUBLISHES[local_id] = {
            "status": "uploading",
            "progress": 10,
            "error": None,
            "post_id": post.id,
            "clip_id": clip_id,
            "permalink": None,
        }

        # 6. Jalankan proses upload & publish di background thread daemon
        post_id = post.id

        def _worker() -> None:
            from app.db.session import SessionLocal

            session_maker = self.session_factory or SessionLocal
            thread_db = session_maker()
            try:
                thread_publish_svc = InstagramPublishService(thread_db, token_manager=self.token_manager)
                thread_post_repo = InstagramPostRepository(thread_db)
                thread_clip_repo = ClipRepository(thread_db)

                def on_progress(stage: str, percent: int) -> None:
                    if local_id in _IG_PUBLISHES:
                        _IG_PUBLISHES[local_id]["status"] = stage
                        _IG_PUBLISHES[local_id]["progress"] = percent

                result = thread_publish_svc.publish_reel(
                    clip_id=clip_id,
                    caption=caption,
                    share_to_feed=share_to_feed,
                    fit_mode=fit_mode,
                    on_progress=on_progress,
                )

                # Publikasi berhasil
                p = thread_post_repo.get(post_id)
                if p:
                    p.status = "published"
                    p.container_id = result.container_id
                    p.media_id = result.media_id
                    p.permalink = result.permalink
                    p.published_at = datetime.now(timezone.utc)
                    p.error_message = None
                    thread_post_repo.save(p)

                c = thread_clip_repo.get(clip_id)
                if c:
                    c.instagram_published = True
                    thread_clip_repo.save(c)

                if local_id in _IG_PUBLISHES:
                    _IG_PUBLISHES[local_id]["status"] = "published"
                    _IG_PUBLISHES[local_id]["progress"] = 100
                    _IG_PUBLISHES[local_id]["permalink"] = result.permalink
                    _IG_PUBLISHES[local_id]["error"] = None

            except PublishUncertainError as e:
                logger.warning("Status publikasi tidak pasti untuk post ID %d: %s", post_id, e)
                thread_post_repo = InstagramPostRepository(thread_db)
                p = thread_post_repo.get(post_id)
                if p:
                    p.status = "unknown"
                    p.error_message = str(e.message)
                    thread_post_repo.save(p)

                if local_id in _IG_PUBLISHES:
                    _IG_PUBLISHES[local_id]["status"] = "unknown"
                    _IG_PUBLISHES[local_id]["error"] = str(e.message)
                # JANGAN ubah flag c.instagram_published

            except Exception as e:
                logger.exception("Publikasi Instagram gagal untuk post ID %d: %s", post_id, e)
                err_msg = getattr(e, "message", str(e))
                thread_post_repo = InstagramPostRepository(thread_db)
                p = thread_post_repo.get(post_id)
                if p:
                    p.status = "failed"
                    p.error_message = err_msg
                    thread_post_repo.save(p)

                if local_id in _IG_PUBLISHES:
                    _IG_PUBLISHES[local_id]["status"] = "failed"
                    _IG_PUBLISHES[local_id]["error"] = err_msg

            finally:
                thread_db.close()

        thread = threading.Thread(target=_worker, name=f"IGPublish-{local_id}", daemon=True)
        thread.start()
        return local_id

    def get_progress(self, local_id: str) -> dict:
        """Ambil progres publish dari dict in-memory (fallback: unknown)."""
        return _IG_PUBLISHES.get(local_id, {"status": "unknown"})

    def latest_post_for_clip(self, clip_id: int) -> InstagramPostModel | None:
        """Ambil riwayat post terbaru untuk klip."""
        return self.post_repo.latest_for_clip(clip_id)

    def list_posts_for_clip(self, clip_id: int) -> list[InstagramPostModel]:
        """Ambil seluruh riwayat post untuk klip (terbaru lebih dulu)."""
        return self.post_repo.list_for_clip(clip_id)

    def mark_stale_failed(self) -> int:
        """Tandai post berstatus uploading/processing yang menggantung sebagai failed saat server restart."""
        stale_posts = self.post_repo.list_stale_active()
        for post in stale_posts:
            post.status = "failed"
            post.error_message = "Terhenti karena aplikasi restart — cek akun Instagram sebelum kirim ulang"
            self.post_repo.save(post)
            logger.info("Menandai stale Instagram post ID %d sebagai failed", post.id)
        return len(stale_posts)
