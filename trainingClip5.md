# TrainingClip 5 — Riwayat Training (Versioning, Bukan File yang Ketimpa)

Konteks: TrainingClip 3 nyimpen hasil training ke `model_metadata.json` yang
**ketimpa** tiap kali "Train Model" diklik ulang — riwayat training sebelumnya
hilang, tidak bisa lihat tren MAE/R² membaik atau tidak dari waktu ke waktu.
Tahap ini mengubahnya jadi tabel database + model file versioned, supaya
`training_dashboard.html` bisa nampilkan histori lengkap.

## Task 1 — Tabel `training_runs`

### Migrasi Alembic baru

```
training_runs
├── id (PK)
├── trained_at (datetime, server_default now)
├── sample_count (int)
├── real_performance_count (int)
├── user_liked_count (int)
├── auto_rejected_count (int)
├── val_mae (float)
├── val_r2 (float)
├── feature_importance (JSONB)
├── model_file_path (string)   -- path ke file model versioned run ini
└── is_active (boolean, default false)  -- model yang SEDANG dipakai predictor.py
```

Buat `app/models/training_run_model.py` (ikuti pola model lain — `Mapped[...]`,
`mapped_column`, dst) dan `app/repositories/training_run_repository.py` dengan
method:

```python
def get_all(self) -> list[TrainingRunModel]:
    """Semua run, terbaru dulu."""
    return list(self.db.query(TrainingRunModel).order_by(TrainingRunModel.trained_at.desc()).all())

def get_active(self) -> TrainingRunModel | None:
    """Run yang sedang aktif dipakai predictor.py."""
    return self.db.query(TrainingRunModel).filter(TrainingRunModel.is_active == True).first()

def set_active(self, run_id: int) -> TrainingRunModel:
    """Set satu run jadi aktif, matikan flag aktif di run lain (cuma boleh 1 aktif)."""
    self.db.query(TrainingRunModel).update({"is_active": False})
    run = self.db.query(TrainingRunModel).filter(TrainingRunModel.id == run_id).first()
    if run is None:
        raise ValueError(f"Training run {run_id} not found")
    run.is_active = True
    self.db.commit()
    self.db.refresh(run)
    return run
```

## Task 2 — Model File Versioned (Bukan Selalu Timpa Satu File)

Ubah `app/ml/trainer.py`: tiap training menghasilkan file model BARU dengan
nama unik, lalu file itu disalin jadi "model aktif" yang dibaca `predictor.py`.
Ini yang memungkinkan rollback ke model lama kalau retrain terbaru ternyata
lebih buruk.

```python
import shutil
from datetime import UTC, datetime

ACTIVE_MODEL_PATH = Path("data/models/score_model.pkl")  # tetap sama, dibaca predictor.py
VERSIONED_MODEL_DIR = Path("data/models/versions")


class ModelTrainer:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.candidate_repo = CandidateRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.run_repo = TrainingRunRepository(db)

    def train(self) -> "TrainingRunModel":
        candidates = self.candidate_repo.get_training_examples()
        if len(candidates) < 20:
            raise ValueError(
                f"Data training terlalu sedikit ({len(candidates)} row). Minimal 20."
            )

        X, y, sample_weight, label_sources = [], [], [], []
        for cand in candidates:
            analysis = self.analysis_repo.get_by_job_and_window(
                cand.job_id, cand.start_time, cand.end_time
            )
            X.append(build_feature_vector(analysis))
            y.append(cand.actual_score)
            sample_weight.append(LABEL_SOURCE_WEIGHTS.get(cand.label_source, 0.5))
            label_sources.append(cand.label_source)

        X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
            X, y, sample_weight, test_size=0.2, random_state=42
        )
        model = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42
        )
        model.fit(X_train, y_train, sample_weight=w_train)
        y_pred = model.predict(X_val)
        mae = mean_absolute_error(y_val, y_pred)
        r2 = r2_score(y_val, y_pred)

        # Simpan versioned file — TIDAK ditimpa run berikutnya.
        VERSIONED_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        versioned_path = VERSIONED_MODEL_DIR / f"score_model_{timestamp}.pkl"
        joblib.dump(model, versioned_path)

        # Salin jadi model aktif — ini yang dibaca predictor.py (path tetap sama,
        # jadi TIDAK PERLU ubah apa pun di predictor.py dari TrainingClip 4).
        shutil.copy(versioned_path, ACTIVE_MODEL_PATH)

        feature_importance = dict(zip(FEATURE_ORDER, model.feature_importances_.tolist()))
        run = self.run_repo.add(TrainingRunModel(
            sample_count=len(candidates),
            real_performance_count=label_sources.count("real_performance"),
            user_liked_count=label_sources.count("user_liked"),
            auto_rejected_count=label_sources.count("auto_rejected"),
            val_mae=round(mae, 3),
            val_r2=round(r2, 3),
            feature_importance=feature_importance,
            model_file_path=str(versioned_path),
            is_active=True,
        ))
        # Matikan flag aktif di run-run sebelumnya.
        self.db.query(TrainingRunModel).filter(TrainingRunModel.id != run.id).update({"is_active": False})
        self.db.commit()

        logger.info("Model trained (run %d): %d samples, val_mae=%.3f, val_r2=%.3f", run.id, len(candidates), mae, r2)
        return run
```

Hapus penggunaan `model_metadata.json` dari TrainingClip 3 — sekarang tabel
`training_runs` yang jadi satu-satunya sumber kebenaran, tidak perlu dua
tempat penyimpanan yang bisa tidak sinkron.

## Task 3 — Endpoint Riwayat & Rollback

Tambahkan di `training_router.py`:

```python
@router.get("/training/runs")
def list_training_runs(service: TrainingRunRepository = Depends(get_training_run_repo)):
    """Semua riwayat training, terbaru dulu."""
    return service.get_all()


@router.post("/training/runs/{run_id}/activate")
def activate_training_run(
    run_id: int,
    repo: TrainingRunRepository = Depends(get_training_run_repo),
):
    """Rollback/aktifkan model dari run tertentu (bukan cuma yang terbaru)."""
    run = repo.get_active_or_404(run_id)  # atau langsung pakai get + cek None
    shutil.copy(run.model_file_path, ACTIVE_MODEL_PATH)
    activated = repo.set_active(run_id)
    logger.info("Model run %d diaktifkan manual (rollback/switch)", run_id)
    return activated
```

## Task 4 — Update `training_dashboard.html`

Ganti bagian yang tadinya baca `model_metadata.json` jadi tabel riwayat:

```html
<table class="table table-sm">
  <thead>
    <tr>
      <th>Tanggal</th><th>Sample</th><th>MAE</th><th>R²</th><th>Sumber Data</th><th></th>
    </tr>
  </thead>
  <tbody>
    {% for run in training_runs %}
    <tr class="{{ 'table-success' if run.is_active else '' }}">
      <td>{{ run.trained_at.strftime('%Y-%m-%d %H:%M') }}</td>
      <td>{{ run.sample_count }}</td>
      <td>{{ run.val_mae }}</td>
      <td>{{ run.val_r2 }}</td>
      <td class="small text-muted">
        {{ run.real_performance_count }} asli / {{ run.user_liked_count }} liked / {{ run.auto_rejected_count }} auto
      </td>
      <td>
        {% if run.is_active %}
          <span class="badge bg-success">Aktif</span>
        {% else %}
          <form method="post" action="/training/runs/{{ run.id }}/activate">
            <button class="btn btn-sm btn-outline-primary">Aktifkan</button>
          </form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
```

Dengan tabel ini Anda bisa langsung lihat: MAE membaik atau tidak tiap retrain,
dan kalau ternyata run terbaru lebih jelek, tinggal klik "Aktifkan" di run
lama — tidak perlu training ulang atau utak-atik file manual.

## Definisi Selesai

- Klik "Train Model" 2x berturut-turut (dengan data training yang sama atau
  beda) → muncul 2 row di `training_runs`, bukan saling menimpa.
- `training_dashboard.html` menampilkan tabel riwayat lengkap, row aktif
  ditandai jelas.
- Klik "Aktifkan" di run yang bukan terbaru → `data/models/score_model.pkl`
  berubah isinya (predictor.py otomatis pakai versi itu di request berikutnya,
  berkat cek `mtime` dari TrainingClip 4), dan badge "Aktif" pindah ke row
  yang benar.
- File lama di `data/models/versions/` tidak terhapus otomatis (biarkan
  menumpuk untuk sekarang — cukup untuk skala data Anda; pembersihan otomatis
  bisa jadi peningkatan lain kalau nanti jumlah run sudah sangat banyak).
