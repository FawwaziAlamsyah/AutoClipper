# Category Training 07 — `ModelTrainer` Jadi Per-Kategori

Bagian 7 dari 14. **Prasyarat: file 01-06 sudah selesai.**

## Task — Tambah Kolom `category_id` di `TrainingRunModel`

### Migrasi Alembic baru

`training_runs.category_id` — INTEGER, **NOT NULL** (beda dari kolom
`category_id` di tabel lain yang nullable — training run WAJIB terikat ke
satu kategori, tidak ada training run tanpa kategori), FK ke `categories.id`.

Update `app/models/training_run_model.py`:

```python
category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
```

## Task — `CandidateRepository.get_training_examples()` Terima `category_id`

Di `app/repositories/candidate_repository.py`:

```python
def get_training_examples(self, category_id: int) -> list[CandidateModel]:
    """Get training examples UNTUK SATU KATEGORI SAJA."""
    return list(
        self.db.query(CandidateModel)
        .filter(
            CandidateModel.is_training_example == True,  # noqa: E712
            CandidateModel.actual_score.isnot(None),
            CandidateModel.category_id == category_id,
        )
        .all()
    )
```

## Task — `ModelTrainer.train()` Terima `category_id`, Path Per-Kategori

Di `app/ml/trainer.py`, ganti signature dan isi method `train()`:

```python
def train(self, category_id: int) -> TrainingRunModel:
    """Latih model UNTUK SATU KATEGORI, simpan versioned + aktif khusus kategori itu."""
    candidates = self.candidate_repo.get_training_examples(category_id=category_id)
    if len(candidates) < 20:
        raise ValueError(
            f"Data training kategori ini terlalu sedikit ({len(candidates)} row). "
            "Minimal 20 contoh (disarankan 100+) sebelum training."
        )

    X, y, sample_weight, label_sources = [], [], [], []
    for cand in candidates:
        analysis = self.analysis_repo.get_by_job_and_window(cand.job_id, cand.start_time, cand.end_time)
        X.append(build_feature_vector(analysis))
        y.append(cand.actual_score)
        sample_weight.append(LABEL_SOURCE_WEIGHTS.get(cand.label_source, 0.5))
        label_sources.append(cand.label_source)

    X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
        X, y, sample_weight, test_size=0.2, random_state=42
    )
    model = GradientBoostingRegressor(n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42)
    model.fit(X_train, y_train, sample_weight=w_train)

    y_pred = model.predict(X_val)
    mae = mean_absolute_error(y_val, y_pred)
    r2 = r2_score(y_val, y_pred)

    # Path sekarang per-kategori, bukan satu file global.
    category_dir = Path(f"data/models/category_{category_id}")
    versioned_dir = category_dir / "versions"
    versioned_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    versioned_path = versioned_dir / f"score_model_{timestamp}.pkl"
    joblib.dump(model, versioned_path)

    active_path = category_dir / "score_model.pkl"
    shutil.copy(versioned_path, active_path)

    feature_importance = dict(zip(FEATURE_ORDER, model.feature_importances_.tolist()))

    run = self.run_repo.add(TrainingRunModel(
        category_id=category_id,
        sample_count=len(candidates),
        real_performance_count=label_sources.count("real_performance"),
        user_liked_count=label_sources.count("user_liked"),
        auto_rejected_count=0,  # dislike sudah tidak lagi masuk training data (lihat file 11)
        val_mae=round(mae, 3),
        val_r2=round(r2, 3),
        feature_importance=feature_importance,
        model_file_path=str(versioned_path),
        is_active=True,
    ))
    # Matikan flag aktif di run LAMA UNTUK KATEGORI YANG SAMA saja — kategori
    # lain tidak boleh saling ganggu status aktifnya.
    self.db.query(TrainingRunModel).filter(
        TrainingRunModel.category_id == category_id,
        TrainingRunModel.id != run.id,
    ).update({"is_active": False})
    self.db.commit()

    logger.info("Model kategori %d trained (run %d): %d samples, val_mae=%.3f", category_id, run.id, len(candidates), mae)
    return run
```

Hapus konstanta `MODEL_PATH`/`VERSIONED_MODEL_DIR` lama di bagian atas file
`trainer.py` — sudah tidak relevan, digantikan path dinamis per kategori
di atas. Tambahkan `import shutil` kalau belum ada.

## Definisi Selesai

- Migrasi berhasil dijalankan, kolom `category_id` ada di `training_runs`.
- `python -m py_compile app/ml/trainer.py app/repositories/candidate_repository.py app/models/training_run_model.py`
  lulus.
- **Belum bisa ditest end-to-end dulu** (endpoint `/training/train` yang
  manggil `ModelTrainer.train(category_id)` masih ada di file 14) — cukup
  pastikan tidak ada syntax/import error dulu di tahap ini.
- `pytest` tetap lulus (test lama yang menyentuh trainer mungkin perlu
  disesuaikan kalau ada — cek dulu apakah ada test yang manggil
  `ModelTrainer.train()` tanpa argumen, kalau ada, itu akan error karena
  sekarang wajib `category_id`; laporkan kalau ketemu, jangan ubah test
  sendiri tanpa konfirmasi).
- **Jangan lanjut ke file 08** sebelum poin di atas terverifikasi.
