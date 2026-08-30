"""Upload clip ke TikTok lewat Content Posting API — mode Inbox/Draft
(video.upload scope), user selesaikan post manual dari app TikTok."""

import logging
import threading
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.core.exceptions.base import ValidationException
from app.repositories.clip_repository import ClipRepository
from app.services.tiktok_auth_service import TikTokAuthService

logger = logging.getLogger(__name__)

INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

# Progress publish aktif — in-memory (app lokal single-user), pola sama
# seperti _DOWNLOADS di download_service.py.
_TIKTOK_PUBLISHES: dict[str, dict] = {}


class TikTokUploadService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.clip_repo = ClipRepository(db)
        self.auth_service = TikTokAuthService(db)

    def init_and_upload(self, clip_id: int) -> str:
        """Init publish + kirim file video. Return publish_id buat di-poll statusnya."""
        clip = self.clip_repo.get(clip_id)
        if clip is None:
            raise ValidationException(f"Clip {clip_id} tidak ditemukan")

        video_path = Path(clip.edited_file_path or clip.file_path)
        if not video_path.exists():
            raise ValidationException(f"File clip tidak ditemukan di disk: {video_path}")

        access_token = self.auth_service.get_valid_access_token()
        video_size = video_path.stat().st_size

        # --- Langkah 1: Init ---
        # Endpoint inbox/draft: body HANYA source_info, TIDAK ada post_info
        # (endpoint ini tak menerima field itu). Video otomatis jadi draft
        # private di inbox user sampai mereka post manual dari app TikTok.
        init_payload = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,
                "total_chunk_count": 1,
            },
        }

        response = httpx.post(
            INIT_URL,
            json=init_payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=15,
        )
        if response.status_code != 200:
            logger.error("TikTok init publish gagal: %s", response.text)
            raise ValidationException(f"Gagal init upload TikTok: {response.text}")

        init_data = response.json().get("data", {})
        publish_id = init_data.get("publish_id")
        upload_url = init_data.get("upload_url")
        if not publish_id or not upload_url:
            raise ValidationException(f"Response init TikTok tidak lengkap: {response.text}")

        logger.info("TikTok init publish sukses untuk clip %d, publish_id=%s", clip_id, publish_id)

        # --- Langkah 2: Upload file video ---
        self._upload_video_bytes(upload_url, video_path, video_size)

        return publish_id

    def _upload_video_bytes(self, upload_url: str, video_path: Path, video_size: int) -> None:
        """PUT file video ke upload_url yang dikasih TikTok di langkah init."""
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        response = httpx.put(
            upload_url,
            content=video_bytes,
            headers={
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                "Content-Type": "video/mp4",
            },
            timeout=120,
        )
        if response.status_code not in (200, 201):
            logger.error("Upload video ke TikTok gagal: %s %s", response.status_code, response.text)
            raise ValidationException(f"Gagal upload video ke TikTok: {response.text}")

        logger.info("Video berhasil di-upload ke TikTok (%d bytes)", video_size)

    def check_status(self, publish_id: str) -> dict:
        """Cek status publish — return dict {status, fail_reason (kalau ada)}."""
        access_token = self.auth_service.get_valid_access_token()

        response = httpx.post(
            STATUS_URL,
            json={"publish_id": publish_id},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=15,
        )
        if response.status_code != 200:
            logger.error("Cek status TikTok gagal: %s", response.text)
            raise ValidationException(f"Gagal cek status TikTok: {response.text}")

        data = response.json().get("data", {})
        return {
            "status": data.get("status"),
            "fail_reason": data.get("fail_reason"),
        }

    def start_publish(self, clip_id: int) -> str:
        """Mulai publish di background thread, return local_id buat polling UI.

        Beda dari publish_id TikTok (baru didapat SETELAH init selesai) — ini
        id sementara buat frontend polling status SEBELUM publish_id TikTok
        ada, supaya UI bisa langsung kasih feedback "sedang upload...".
        """
        local_id = f"tt_{uuid.uuid4().hex[:8]}"
        _TIKTOK_PUBLISHES[local_id] = {"status": "uploading", "tiktok_publish_id": None, "error": None, "progress": 15}

        def _run() -> None:
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                service = TikTokUploadService(db)
                tiktok_publish_id = service.init_and_upload(clip_id)
                _TIKTOK_PUBLISHES[local_id]["tiktok_publish_id"] = tiktok_publish_id
                _TIKTOK_PUBLISHES[local_id]["status"] = "processing"
                _TIKTOK_PUBLISHES[local_id]["progress"] = 90

                # Poll sampai selesai (maks ~4 menit — video >50MB butuh waktu
                # lebih dari 60 detik; status "SEND_TO_USER_INBOX" baru muncul
                # setelah TikTok selesai transkode).
                # Sasaran sukses flow inbox: status "SEND_TO_USER_INBOX" (video
                # sudah masuk ke inbox user). "PUBLISH_COMPLETE" itu untuk flow
                # Direct Post, bukan inbox.
                for _ in range(120):
                    time.sleep(2)
                    result = service.check_status(tiktok_publish_id)
                    if result["status"] in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
                        _TIKTOK_PUBLISHES[local_id]["status"] = "complete"
                        _TIKTOK_PUBLISHES[local_id]["progress"] = 100
                        return
                    if result["status"] == "FAILED":
                        _TIKTOK_PUBLISHES[local_id]["status"] = "error"
                        _TIKTOK_PUBLISHES[local_id]["error"] = result.get("fail_reason", "Unknown error")
                        return

                _TIKTOK_PUBLISHES[local_id]["status"] = "timeout"
            except Exception as e:
                logger.error("Publish TikTok gagal untuk clip %d: %s", clip_id, e)
                _TIKTOK_PUBLISHES[local_id]["status"] = "error"
                _TIKTOK_PUBLISHES[local_id]["error"] = str(e)
            finally:
                db.close()

        threading.Thread(target=_run, daemon=True).start()
        return local_id

    def get_publish_progress(self, local_id: str) -> dict:
        return _TIKTOK_PUBLISHES.get(local_id, {"status": "unknown"})