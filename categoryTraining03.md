# Category Training 03 — Wipe Data Training Lama

Bagian 3 dari 14. **Prasyarat: file 01-02 sudah selesai.**

Konteks: data training yang sudah terkumpul sebelumnya belum ada
kategorinya. Sesuai keputusan user, mulai dari nol per kategori — bukan
migrasi paksa/tebak-tebak kategori dari data lama.

## Task — Reset Data Training di Migrasi yang Sama/Terpisah

Tambahkan operasi ini di migrasi Alembic (pakai `op.execute(...)`, jalan
otomatis pas `alembic upgrade head` — boleh ditambahkan ke migrasi file 02
kalau belum di-apply, atau bikin migrasi baru terpisah kalau sudah):

```python
def upgrade() -> None:
    # (kalau ini migrasi baru terpisah, tidak ada operasi schema lain di sini)

    # Reset seluruh data training lama — belum punya kategori, mulai dari nol
    # sesuai keputusan user (bukan migrasi paksa/tebak-tebak kategori).
    op.execute("""
        UPDATE candidates
        SET is_training_example = false,
            actual_score = NULL,
            label_source = NULL
        WHERE is_training_example = true
    """)
    op.execute("DELETE FROM training_runs")
```

Tambahkan catatan di deskripsi migrasi (docstring/comment di file migrasi)
bahwa operasi ini **destruktif dan disengaja** — supaya kalau nanti ada yang
baca riwayat migrasi, jelas ini bukan bug.

## Task — Bersihkan File Model Lama (Manual, Bukan Bagian Migrasi)

Jalankan manual lewat terminal SETELAH migrasi berhasil (bukan lewat kode —
supaya tidak ada risiko script hapus file jalan tanpa sengaja):

```bash
rm -f data/models/score_model.pkl
rm -rf data/models/versions
```

## Definisi Selesai

- Migrasi berhasil dijalankan.
- `SELECT COUNT(*) FROM candidates WHERE is_training_example = true;` hasilnya
  **0**.
- `SELECT COUNT(*) FROM training_runs;` hasilnya **0**.
- File `data/models/score_model.pkl` dan folder `data/models/versions/`
  sudah dihapus manual.
- **Jangan lanjut ke file 04** sebelum poin di atas terverifikasi.
