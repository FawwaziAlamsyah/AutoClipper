# TikTok 04 — Polling Status & Endpoint Publish

Bagian 4 dari 5. **Prasyarat: `tiktok01.md`-`tiktok03.md` sudah selesai.**

Upload video ke TikTok itu proses async di sisi mereka — setelah kirim
file (`tiktok03.md`), TikTok butuh waktu proses di background, kita harus
poll status-nya sampai selesai. Sama polanya dengan `_DOWNLOADS` in-memory
progress tracking di `download_service.py` yang sudah ada.

## Task — Tambah `check_status()` di `TikTokUploadService`

Tambahkan di `app/services/tiktok_upload_service.py`:

```python
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

# ... di dalam class TikTokUploadService, tambahkan method:

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
        "status": data.get("status"),  # PROCESSING_UPLOAD | PUBLISH_COMPLETE | FAILED, dst
        "fail_reason": data.get("fail_reason"),
    }
```

## Task — Progress Tracker In-Memory (Pola Sama Seperti `_DOWNLOADS`)

Di file yang sama, bagian atas (setelah import, sebelum class):

```python
# Store progress publish aktif — in-memory (app lokal single-user),
# pola sama seperti _DOWNLOADS di download_service.py.
_TIKTOK_PUBLISHES: dict[str, dict] = {}
```

## Task — `start_publish()` — Jalankan di Background Thread

Tambahkan method baru di `TikTokUploadService`:

```python
def start_publish(self, clip_id: int) -> str:
    """Mulai publish di background thread, return publish_id lokal buat polling UI.

    Beda dari publish_id TikTok (baru didapat SETELAH init selesai) — ini
    id sementara buat frontend polling status SEBELUM publish_id TikTok
    ada, supaya UI bisa langsung kasih feedback "sedang upload..." tanpa
    nunggu init selesai dulu.
    """
    import threading
    import uuid

    local_id = f"tt_{uuid.uuid4().hex[:8]}"
    _TIKTOK_PUBLISHES[local_id] = {"status": "uploading", "tiktok_publish_id": None, "error": None}

    def _run():
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            service = TikTokUploadService(db)
            tiktok_publish_id = service.init_and_upload(clip_id)
            _TIKTOK_PUBLISHES[local_id]["tiktok_publish_id"] = tiktok_publish_id
            _TIKTOK_PUBLISHES[local_id]["status"] = "processing"

            # Poll sampai selesai (maks ~60 detik, TikTok biasanya proses cepat untuk video pendek)
            import time
            for _ in range(30):
                time.sleep(2)
                result = service.check_status(tiktok_publish_id)
                if result["status"] == "PUBLISH_COMPLETE":
                    _TIKTOK_PUBLISHES[local_id]["status"] = "complete"
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
```

## Task — Endpoint Router

Tambahkan di `app/routers/tiktok_router.py`:

```python
@router.post("/publish/{clip_id}")
def publish_clip_to_tiktok(
    clip_id: int,
    service: TikTokUploadService = Depends(get_tiktok_upload_service),
) -> dict:
    """Mulai proses publish clip ke TikTok (mode draft/SELF_ONLY), return local_id buat polling."""
    local_id = service.start_publish(clip_id)
    return {"local_id": local_id, "status": "uploading"}


@router.get("/publish/{local_id}/status")
def get_publish_status(
    local_id: str,
    service: TikTokUploadService = Depends(get_tiktok_upload_service),
) -> dict:
    """Polling status publish dari frontend."""
    return service.get_publish_progress(local_id)
```

Tambahkan `get_tiktok_upload_service` di `dependencies.py`, dan import
`TikTokUploadService` di `tiktok_router.py`.

## Definisi Selesai

- `python -m py_compile app/services/tiktok_upload_service.py app/routers/tiktok_router.py`
  lulus.
- `POST /tiktok/publish/{clip_id}` pada clip yang valid (dengan akun TikTok
  sudah connect) → return `{"local_id": "tt_...", "status": "uploading"}`
  segera (tidak nunggu upload selesai — bukti background thread jalan).
- Polling `GET /tiktok/publish/{local_id}/status` berkala → status berubah
  dari `uploading` → `processing` → `complete` (atau `error` kalau gagal,
  dengan pesan jelas di `error`).
- Cek TikTok app di HP Anda → video muncul di draft/inbox (private,
  `SELF_ONLY`), siap Anda tap "Post" manual.
- `pytest` tetap lulus.
- **Jangan lanjut ke `tiktok05.md`** sebelum poin di atas terverifikasi —
  ini tes end-to-end paling penting di seluruh seri TikTok.
