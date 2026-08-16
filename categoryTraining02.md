# Category Training 02 — Kolom `category_id` di `candidates` dan `jobs`

Bagian 2 dari 14. **Prasyarat: file 01 harus sudah selesai** (tabel
`categories` sudah ada). Kalau belum, berhenti dan kerjakan file 01 dulu.

## Task — Tambah Kolom `category_id`

### Migrasi Alembic baru

- `candidates.category_id` — INTEGER, nullable, FK ke `categories.id`,
  **`ondelete="SET NULL"`** (kalau kategori dihapus, candidate TIDAK ikut
  terhapus, cuma referensinya jadi kosong).
- `jobs.category_id` — INTEGER, nullable, FK ke `categories.id`, sama
  `ondelete="SET NULL"`.

### Update `app/models/candidate_model.py`

Tambahkan kolom dan relationship:

```python
category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
category: Mapped["CategoryModel | None"] = relationship(back_populates="candidates")
```

### Update `app/models/job_model.py`

```python
category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
category: Mapped["CategoryModel | None"] = relationship(back_populates="jobs")
```

### Update `app/models/category_model.py` (dari file 01)

Sekarang kolom FK-nya sudah ada di kedua sisi, tambahkan relationship balik:

```python
candidates: Mapped[list["CandidateModel"]] = relationship(back_populates="category")
jobs: Mapped[list["JobModel"]] = relationship(back_populates="category")
```

## Definisi Selesai

- Migrasi berhasil dijalankan, kolom `category_id` ada di `candidates` dan
  `jobs` (cek lewat `\d candidates` / `\d jobs` di psql atau tool serupa).
- `python -m py_compile app/models/candidate_model.py app/models/job_model.py app/models/category_model.py`
  lulus tanpa error.
- Jalankan `pytest` — harus tetap lulus (kolom baru nullable, tidak boleh
  mengubah perilaku yang sudah ada).
- **Jangan lanjut ke file 03** sebelum poin di atas terverifikasi.
