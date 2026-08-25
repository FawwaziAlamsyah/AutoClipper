# TikTok 03 — Upload Service: Init & Kirim Video

Bagian 3 dari 5. **Prasyarat: `tiktok01.md`-`tiktok02.md` sudah selesai**
(minimal 1 akun TikTok sudah connect, ada row di `tiktok_accounts`).

Alur Content Posting API TikTok itu 3 langkah: **init** (kasih tahu TikTok
mau upload apa) → **upload** (kirim file video-nya) → **poll status**
(cek sampai selesai diproses). File ini cover 2 langkah pertama,
`tiktok04.md` lanjut ke polling.

**Catatan jujur**: saya tidak bisa test kode ini langsung ke API TikTok
(sandbox saya tidak ada akses internet + tidak punya app TikTok
terdaftar). Field/format request di bawah ini berdasar dokumentasi resmi
Content Posting API — kalau ada field yang TikTok tolak/beda nama saat
Anda coba beneran, itu kemungkinan API mereka sedikit berubah, cocokkan
dengan dokumentasi terbaru di developers.tiktok.com.

## Task — `TikTokUploadService`

`app/services/tiktok_upload_service.py` (file baru):

```python
"""Upload clip ke TikTok lewat Content Posting API (mode draft/SELF_ONLY)."""

import logging
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.core.exceptions.base import ValidationException
from app.repositories.clip_repository import ClipRepository
from app.services.tiktok_auth_service import TikTokAuthService

logger = logging.getLogger(__name__)

INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"


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
        init_payload = {
            "post_info": {
                # SENGAJA HARDCODE SELF_ONLY — mode unaudited TikTok WAJIB private,
                # jangan diubah ke PUBLIC_TO_EVERYONE sebelum app lolos audit
                # (lihat tiktokSetup.md poin 5-6).
                "privacy_level": "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,   # upload sekaligus (1 chunk) — clip pendek, tidak perlu chunking rumit
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
            timeout=120,  # upload bisa agak lama tergantung ukuran file + koneksi
        )
        if response.status_code not in (200, 201):
            logger.error("Upload video ke TikTok gagal: %s %s", response.status_code, response.text)
            raise ValidationException(f"Gagal upload video ke TikTok: {response.text}")

        logger.info("Video berhasil di-upload ke TikTok (%d bytes)", video_size)
```

## Definisi Selesai

- `python -m py_compile app/services/tiktok_upload_service.py` lulus.
- **Belum bisa ditest end-to-end** — endpoint yang manggil service ini dan
  polling status ada di `tiktok04.md`. Cukup pastikan tidak ada syntax
  error dan struktur request sesuai dokumentasi TikTok yang Anda baca
  sendiri saat ini (cek ulang ke developers.tiktok.com kalau ragu, API
  bisa saja sedikit berubah dari yang saya tulis).
- `pytest` tetap lulus.
- **Jangan lanjut ke `tiktok04.md`** sebelum poin di atas terverifikasi.
