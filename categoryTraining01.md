# Category Training 01 — Tabel & Model Kategori

Bagian 1 dari 14 seri Category Training. Kerjakan berurutan sesuai nomor,
JANGAN loncat ke file lain sebelum file ini selesai dan Definisi Selesai-nya
lulus. File ini isinya CUMA satu hal: bikin tabel `categories`.

Konteks besar (baca sekali, berlaku untuk seluruh seri 01-14): sistem
training sekarang cuma 1 model global. Mau diubah jadi per-kategori (user
bisa bikin kategori kayak "Gaming Funny", "Podcast Sedih", dll, masing-masing
punya model scoring sendiri).

## Task — Tabel `categories` + Model

### Migrasi Alembic baru

```
categories
├── id (PK)
├── name (string, unique, mis. "Gaming Funny")
├── created_at
└── updated_at
```

### `app/models/category_model.py` (file baru)

```python
"""SQLAlchemy model for the categories table."""

from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CategoryModel(Base):
    """Kategori clip style yang bisa dibuat user (Gaming Funny, Podcast Sedih, dst)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Jangan tambahkan `relationship()` ke `CandidateModel`/`JobModel` dulu di
file ini — itu bagian file 02 (setelah kolom `category_id` ada di kedua
tabel itu). Kalau ditambahkan sekarang, akan error karena kolom FK-nya
belum ada.

## Definisi Selesai

- Migrasi berhasil dijalankan (`alembic upgrade head`), tabel `categories`
  ada di database.
- `python -m py_compile app/models/category_model.py` lulus tanpa error.
- Cek manual lewat `psql`/DB client: `SELECT * FROM categories;` jalan
  tanpa error (tabel kosong, itu wajar).
- **Jangan lanjut ke file 02** sebelum poin di atas terverifikasi.
