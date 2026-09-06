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
        #
        # Aturan chunk TikTok (docs resmi — Media Transfer Guide):
        # - Video <= 64 MB -> upload whole: chunk_size = video_size, total = 1
        # - Video > 64 MB  -> wajib multi-chunk, chunk_size = 64 MB, minimal 2 chunk
        #   (lihat catatan di _calculate_chunks soal kasus tepian 64-128MB)
        # - Chunk terakhir menampung SISA bytes (trailing), boleh lebih besar
        #   dari chunk_size (maks 128 MB) — bukan dipotong sama rata.
        chunk_size, total_chunks = self._calculate_chunks(video_size)

        # Log SEBELUM request dikirim (bukan cuma setelah sukses) — supaya kalau
        # init gagal/ditolak TikTok, angka video_size/chunk_size/total_chunks
        # yang sebenarnya dikirim tetap kelihatan di log untuk debug.
        logger.info(
            "TikTok init request: clip %d, video_size=%d (%.1fMB), chunk_size=%d (%.1fMB), total_chunks=%d",
            clip_id, video_size, video_size / 1024 / 1024,
            chunk_size, chunk_size / 1024 / 1024, total_chunks,
        )

        init_payload = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
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
            logger.error(
                "TikTok init publish gagal (video_size=%d, chunk_size=%d, total_chunks=%d): %s",
                video_size, chunk_size, total_chunks, response.text,
            )
            raise ValidationException(f"Gagal init upload TikTok: {response.text}")

        init_data = response.json().get("data", {})
        publish_id = init_data.get("publish_id")
        upload_url = init_data.get("upload_url")
        if not publish_id or not upload_url:
            raise ValidationException(f"Response init TikTok tidak lengkap: {response.text}")

        logger.info("TikTok init publish sukses untuk clip %d, publish_id=%s", clip_id, publish_id)

        # --- Langkah 2: Upload file video (chunked PUT) ---
        # chunk_size & total_chunks dikirim apa adanya dari hasil hitung di atas
        # (TIDAK dihitung ulang di sini) supaya nilai yang dipakai saat init dan
        # saat upload selalu identik.
        self._upload_video_bytes(upload_url, video_path, video_size, chunk_size, total_chunks)

        return publish_id

    @staticmethod
    def _calculate_chunks(video_size: int) -> tuple[int, int]:
        """Hitung (chunk_size, total_chunk_count) sesuai aturan resmi TikTok
        (Media Transfer Guide — Chunk restrictions).

        PENTING (dikonfirmasi lewat 3 percobaan gagal nyata di video 78.8MB,
        bukan tebakan lagi): field `chunk_size` itu HARD CAP di 64MB TANPA
        pengecualian — termasuk untuk chunk tunggal/final. Kalimat resmi
        "final chunk can be greater than chunk_size (up to 128MB)" itu bicara
        soal byte FISIK yang dikirim di request terakhir, BUKAN nilai field
        chunk_size di JSON — field itu sendiri selalu harus <=64MB.

        Konsekuensinya:
        - video_size <= 64MB -> 1 chunk, chunk_size = video_size (pola resmi
          "whole upload", TIDAK diperluas ke 128MB — itu asumsi saya
          sebelumnya yang sudah terbukti salah).
        - video_size > 64MB  -> WAJIB multi-chunk. chunk_size dihitung DINAMIS
          (bukan konstanta 64MB tetap) supaya total_chunk_count = floor(
          video_size / chunk_size) benar-benar konsisten dan chunk_size tetap
          <= 64MB:
            total_chunk_count = ceil(video_size / 64MB)   # jumlah chunk minimum
            chunk_size = floor(video_size / total_chunk_count)  # <=64MB, dan
              floor(video_size / chunk_size) dijamin == total_chunk_count
              (sifat matematis floor-division, bukan trial-error).
        """
        _MAX_CHUNK = 64 * 1024 * 1024  # 64 MB — batas MUTLAK field chunk_size

        if video_size <= _MAX_CHUNK:
            return video_size, 1

        total_chunks = -(-video_size // _MAX_CHUNK)  # ceil: jumlah chunk minimum
        chunk_size = video_size // total_chunks       # floor: <=64MB, konsisten
        return chunk_size, total_chunks

    def _upload_video_bytes(
        self,
        upload_url: str,
        video_path: Path,
        video_size: int,
        chunk_size: int,
        total_chunks: int,
    ) -> None:
        """Upload file video ke TikTok dengan chunked PUT sesuai docs resmi.

        - chunk_size & total_chunks diterima dari caller (init_and_upload),
          TIDAK dihitung ulang di sini — supaya konsisten dengan nilai yang
          sudah dikirim ke endpoint init.
        - Chunk terakhir membawa SEMUA sisa bytes (trailing) — bisa lebih besar
          ATAU lebih kecil dari chunk_size, tergantung total_chunks dan video_size.
        - Setiap chunk dikirim satu PUT berurutan (sequential, bukan paralel)
          dengan Content-Range yang tepat.
        - Response 206 = chunk diterima (masih ada chunk berikutnya),
          200/201 = chunk terakhir diterima, upload selesai.
        """
        with open(video_path, "rb") as f:
            for chunk_idx in range(total_chunks):
                offset = chunk_idx * chunk_size
                is_last = chunk_idx == total_chunks - 1

                if not is_last:
                    data = f.read(chunk_size)
                else:
                    # Chunk terakhir: baca SEMUA sisa bytes (trailing digabung),
                    # bukan cuma chunk_size — bisa lebih besar atau lebih kecil
                    # dari chunk_size tergantung sisa file.
                    data = f.read()

                if not data:
                    # Safety net: kalau ternyata total_chunks dihitung kebesaran
                    # (harusnya tidak terjadi kalau _calculate_chunks benar),
                    # jangan kirim PUT kosong ke TikTok.
                    logger.warning(
                        "Chunk %d/%d kosong, dilewati (kemungkinan total_chunks salah hitung)",
                        chunk_idx + 1, total_chunks,
                    )
                    break

                end_byte = offset + len(data) - 1

                response = httpx.put(
                    upload_url,
                    content=data,
                    headers={
                        "Content-Range": f"bytes {offset}-{end_byte}/{video_size}",
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(data)),
                    },
                    timeout=120,
                )

                # TikTok: 206 = partial accepted (masih ada chunk berikutnya),
                # 200/201 = accepted, upload selesai (biasanya di chunk terakhir).
                expected = (200, 201) if is_last else (200, 201, 206)
                if response.status_code not in expected:
                    logger.error(
                        "Upload chunk %d/%d ke TikTok gagal: %s %s",
                        chunk_idx + 1, total_chunks,
                        response.status_code, response.text,
                    )
                    raise ValidationException(
                        f"Gagal upload chunk {chunk_idx + 1}/{total_chunks} ke TikTok: {response.text}"
                    )

                logger.info(
                    "Chunk %d/%d berhasil di-upload (status %d, %d bytes, offset %d-%d)",
                    chunk_idx + 1, total_chunks,
                    response.status_code, len(data), offset, end_byte,
                )

        logger.info("Video berhasil di-upload ke TikTok (%d bytes, %d chunk)", video_size, total_chunks)

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
                        # Tandai clip sudah berhasil terkirim ke inbox TikTok (persist
                        # di DB biar keliatan di UI candidate/detail walau app restart).
                        try:
                            clip = service.clip_repo.get(clip_id)
                            if clip:
                                clip.tiktok_uploaded = True
                                db.commit()
                        except Exception:
                            logger.exception("Gagal tandai tiktok_uploaded clip %d", clip_id)
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