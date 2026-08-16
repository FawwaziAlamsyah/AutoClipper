# Category Training 09 — `score_engine.py` Kirim `category_id` dari Job

Bagian 9 dari 14. **Prasyarat: file 01-08 sudah selesai.**

## Task — Update `calculate_for_job()`

Di `app/services/score_engine.py`:

```python
def calculate_for_job(self, job_id: int) -> float:
    job = self.job_repo.get(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    candidates = self.candidate_repo.get_by_job(job_id)
    if not candidates:
        logger.warning("No candidates found for job %d", job_id)
        return 0.0

    for candidate in candidates:
        breakdown = self._calculate_score_breakdown(job_id, candidate, job.category_id)
        # ... sisa logic (final_score = sum(...), commit, dst) TIDAK BERUBAH
```

## Task — Update `_calculate_score_breakdown()`

Ubah signature supaya terima `category_id`, dan teruskan ke `predict_score`:

```python
def _calculate_score_breakdown(self, job_id: int, candidate, category_id: int | None) -> dict:
    # ... bagian awal (ambil analysis, hitung weighted-sum breakdown) TIDAK BERUBAH

    model_score = None
    if settings.USE_TRAINED_SCORE_MODEL:
        model_score = predict_score(cand_analysis, category_id)  # tambah category_id

    # ... sisa logic (breakdown["_meta"] = {...}) TIDAK BERUBAH
```

Cari baris pemanggilan `predict_score(...)` yang sudah ada (dari
implementasi sebelumnya) untuk tahu persis di mana menambahkan parameter
`category_id` — cuma nambah 1 argumen ke pemanggilan yang sudah ada, bukan
menulis ulang seluruh method.

## Definisi Selesai

- `python -m py_compile app/services/score_engine.py` lulus.
- Proses 1 video test dengan `category_id=None` (tidak pilih kategori di
  Upload) → `score_breakdown._meta.scoring_method` = `"weighted_sum"`
  (fallback jalan seperti sebelumnya, tidak ada regresi).
- Proses 1 video test dengan `category_id` = kategori yang BELUM punya
  model (dari file 04, kategori baru dibuat tapi belum pernah training) →
  tetap `"weighted_sum"`, tidak crash walau kategori dipilih.
- `pytest` tetap lulus.
- **Jangan lanjut ke file 10** sebelum poin di atas terverifikasi.
