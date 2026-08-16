# Category Training 05 — Hapus `content_type`, Ganti `clip_style` Jadi `category_id`

Bagian 5 dari 14. **Prasyarat: file 01-04 sudah selesai.**

**Temuan penting**: `content_type` dan `clip_style` yang ada di form Upload
sekarang **tidak pernah dibaca oleh pipeline manapun** — cek
`process_service.py`, tidak ada satu baris pun yang pakai `req.content_type`
atau `req.clip_style`. Jadi pekerjaan ini BUKAN "mencabut fitur yang jalan",
cuma mengisi sesuatu yang selama ini kosong.

## Task — Schema

### `app/schemas/process_schema.py`

```python
# HAPUS baris ini sepenuhnya:
# content_type: str = Field("podcast", description="...")
# clip_style: str = Field("viral", description="...")

# GANTI dengan:
category_id: int | None = Field(
    None, description="ID kategori clip style (dari tabel categories). None = scoring default/weighted-sum."
)
```

### `app/schemas/job_schema.py`

Hapus `content_type` dan `clip_style`, ganti `category_id: int | None = None`
— pola sama seperti di atas.

## Task — `ProcessService.create_job()`

Di `app/services/process_service.py`:

```python
def create_job(self, video_id: int, job_type: str = "discovery", category_id: int | None = None) -> int:
    """Buat job baru, simpan category_id kalau ada (dipakai scoring nanti)."""
    job = JobModel(video_id=video_id, job_type=job_type, category_id=category_id, status="pending")
    self.db.add(job)
    self.db.commit()
    self.db.refresh(job)
    return job.id
```

## Task — Update Pemanggil di Router

Di `app/routers/video_router.py`, endpoint `process_video()`:

```python
job_id = service.create_job(video_id, category_id=req.category_id)
```

## Definisi Selesai

- `python -m py_compile app/schemas/process_schema.py app/schemas/job_schema.py app/services/process_service.py app/routers/video_router.py`
  lulus tanpa error.
- Panggil `POST /videos/{id}/process` dengan body `{"category_id": null}` →
  job tetap berhasil dibuat (backward compatible, category_id opsional).
- Cek di database: job yang baru dibuat, kolom `category_id`-nya sesuai
  yang dikirim (NULL kalau tidak dikirim).
- `pytest` tetap lulus.
- **Jangan lanjut ke file 06** sebelum poin di atas terverifikasi.
