# Category Training 13 — `TrainingRunRepository` & `TrainingStatsService` Per Kategori

Bagian 13 dari 14. **Prasyarat: file 01-12 sudah selesai.**

## Task — `TrainingRunRepository`: Semua Method Di-scope per Kategori

Di `app/repositories/training_run_repository.py`, ganti `get_all()`,
`get_active()`, `set_active()`:

```python
def get_all(self, category_id: int) -> list[TrainingRunModel]:
    """Semua run UNTUK SATU KATEGORI, terbaru dulu."""
    return list(
        self.db.query(TrainingRunModel)
        .filter(TrainingRunModel.category_id == category_id)
        .order_by(TrainingRunModel.trained_at.desc())
        .all()
    )

def get_active(self, category_id: int) -> TrainingRunModel | None:
    """Run yang sedang aktif UNTUK SATU KATEGORI."""
    return (
        self.db.query(TrainingRunModel)
        .filter(TrainingRunModel.category_id == category_id, TrainingRunModel.is_active == True)  # noqa: E712
        .first()
    )

def set_active(self, run_id: int) -> TrainingRunModel:
    """Set satu run jadi aktif — cuma matikan flag run LAIN DI KATEGORI YANG SAMA."""
    run = self.db.query(TrainingRunModel).filter(TrainingRunModel.id == run_id).first()
    if run is None:
        raise ValueError(f"Training run {run_id} not found")
    self.db.query(TrainingRunModel).filter(
        TrainingRunModel.category_id == run.category_id
    ).update({"is_active": False})
    run.is_active = True
    self.db.commit()
    self.db.refresh(run)
    return run
```

`get(run_id)` (kalau ada, ambil 1 run by ID) tidak perlu diubah — sudah
otomatis spesifik ke 1 run, tidak butuh scoping tambahan.

## Task — `TrainingStatsService.get_stats(category_id)`

Di `app/services/training_stats_service.py`:

```python
def get_stats(self, category_id: int) -> dict:
    """Return jumlah training example + riwayat runs UNTUK SATU KATEGORI."""
    candidates = self.candidate_repo.get_training_examples(category_id=category_id)

    counts_by_source = {src: 0 for src in LABEL_SOURCES}
    for cand in candidates:
        src = cand.label_source or "unknown"
        if src in counts_by_source:
            counts_by_source[src] += 1

    total = len(candidates)
    training_runs = self.run_repo.get_all(category_id)
    active_run = self.run_repo.get_active(category_id)

    for run in training_runs:
        if run.feature_importance:
            run.feature_importance = dict(
                sorted(run.feature_importance.items(), key=lambda x: x[1], reverse=True)
            )

    return {
        "total": total,
        "counts_by_source": counts_by_source,
        "training_runs": training_runs,
        "active_run": active_run,
    }
```

Cari definisi `LABEL_SOURCES` di file yang sama (konstanta di bagian atas)
— hapus `"user_disliked"`/`"auto_rejected"` dari daftar itu kalau masih ada
(sesuai file 11, dislike tidak pernah jadi training example lagi, jadi
hitungannya akan selalu 0 — lebih jujur dihilangkan dari tampilan daripada
nampilin angka nol yang membingungkan). Sisakan `("real_performance",
"user_liked")` saja.

## Definisi Selesai

- `python -m py_compile app/repositories/training_run_repository.py app/services/training_stats_service.py`
  lulus.
- **Belum bisa ditest end-to-end** (endpoint yang manggil method-method ini
  ada di file 14) — cukup pastikan tidak ada syntax error dan signature
  method sudah benar (terima `category_id`).
- `pytest` tetap lulus.
- **Jangan lanjut ke file 14** sebelum poin di atas terverifikasi.
