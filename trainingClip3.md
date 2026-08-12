# TrainingClip 3 — Feature Builder & Model Trainer

Konteks: TrainingClip 1 & 2 sudah menyiapkan 3 sumber data training
(`real_performance`, `user_liked`, `auto_rejected`) lengkap dengan
`label_source` untuk bobot kepercayaan. Tahap ini membangun model yang
benar-benar belajar dari data itu — **belum** dipakai untuk scoring live,
itu di TrainingClip 4.

## Task 1 — Modul Baru `app/ml/`

Buat folder baru `app/ml/` (terpisah dari `ai_modules/` — `ai_modules/` isinya
analyzer per-window, `app/ml/` isinya model yang MENGGABUNGKAN hasil semua
analyzer jadi satu skor, jadi secara konsep beda tanggung jawab):

```
app/ml/
├── __init__.py
├── feature_builder.py   # analysis_results -> feature vector konsisten
└── trainer.py            # ambil data training, fit model, simpan ke disk
```

## Task 2 — `feature_builder.py`

Feature vector HARUS pakai urutan kolom yang sama persis antara training dan
nanti saat prediksi live (TrainingClip 4) — kalau urutannya beda, model akan
salah baca input.

```python
"""Ubah analysis_results jadi feature vector konsisten untuk model scoring."""

FEATURE_ORDER = [
    "llm_content", "hook", "story", "voice_emotion", "face_emotion",
    "gesture", "eye_contact", "scene", "audio", "context", "ending",
]


def build_feature_vector(analysis_results: list) -> list[float]:
    """Ubah list AnalysisResultModel (untuk SATU window/candidate) jadi vector.

    Kategori yang tidak ada hasil analyzer-nya (mis. analyzer mati/skip)
    diisi 0.5 (netral) — SAMA seperti fallback lama di score_engine, supaya
    training data konsisten dengan cara live scoring memperlakukan data hilang.
    """
    by_type: dict[str, list[float]] = {}
    for result in analysis_results:
        by_type.setdefault(result.analyzer_type, []).append(result.score or 0.0)

    vector = []
    for feature_name in FEATURE_ORDER:
        scores = by_type.get(feature_name)
        if not scores:
            vector.append(0.5)
        else:
            vector.append(sum(scores) / len(scores))
    return vector
```

## Task 3 — `trainer.py`

```python
"""Latih model scoring dari data training yang terkumpul."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.ml.feature_builder import FEATURE_ORDER, build_feature_vector
from app.repositories.analysis_result_repository import AnalysisResultRepository
from app.repositories.candidate_repository import CandidateRepository

logger = logging.getLogger(__name__)

# Bobot kepercayaan per sumber label — data performa nyata paling dipercaya,
# auto-harvest paling rendah karena cuma pseudo-label.
LABEL_SOURCE_WEIGHTS = {
    "real_performance": 1.0,
    "user_liked": 0.6,
    "auto_rejected": 0.3,
}

MODEL_PATH = Path("data/models/score_model.pkl")
METADATA_PATH = Path("data/models/model_metadata.json")


class ModelTrainer:
    """Latih dan simpan model scoring dari training_example candidates."""

    def __init__(self, db: Session) -> None:
        """Init dengan DB session dan repositories."""
        self.db = db
        self.candidate_repo = CandidateRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)

    def train(self) -> dict:
        """Latih model, simpan ke disk, return metrics untuk ditampilkan di UI."""
        candidates = self.candidate_repo.get_training_examples()
        if len(candidates) < 20:
            raise ValueError(
                f"Data training terlalu sedikit ({len(candidates)} row). "
                "Minimal 20 contoh (disarankan 100+) sebelum training."
            )

        X, y, sample_weight = [], [], []
        for cand in candidates:
            analysis = self.analysis_repo.get_by_job_and_window(
                cand.job_id, cand.start_time, cand.end_time
            )
            X.append(build_feature_vector(analysis))
            y.append(cand.actual_score)
            sample_weight.append(LABEL_SOURCE_WEIGHTS.get(cand.label_source, 0.5))

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

        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_PATH)

        feature_importance = dict(zip(FEATURE_ORDER, model.feature_importances_.tolist()))
        metadata = {
            "trained_at": datetime.now(UTC).isoformat(),
            "sample_count": len(candidates),
            "by_label_source": {
                src: sum(1 for c in candidates if c.label_source == src)
                for src in LABEL_SOURCE_WEIGHTS
            },
            "val_mae": round(mae, 3),
            "val_r2": round(r2, 3),
            "feature_importance": feature_importance,
            "feature_order": FEATURE_ORDER,
        }
        METADATA_PATH.write_text(json.dumps(metadata, indent=2))

        logger.info(
            "Model trained: %d samples, val_mae=%.3f, val_r2=%.3f",
            len(candidates), mae, r2,
        )
        return metadata
```

Tambahkan `get_training_examples()` di `CandidateRepository` (filter
`is_training_example=True AND actual_score IS NOT NULL`), dan
`get_by_job_and_window(job_id, start_time, end_time)` di
`AnalysisResultRepository` (filter job_id + start_time + end_time persis sama
— ini valid karena `analysis_service` selalu membuat `analysis_results` dengan
start/end yang sama persis dengan window yang jadi candidate-nya).

## Task 4 — Endpoint & Halaman "Train Model"

### Endpoint — `app/routers/training_router.py` (boleh file baru atau extend yang sudah ada dari TrainingClip 2)

```python
@router.post("/training/train")
def train_model(service: ModelTrainer = Depends(get_model_trainer)):
    """Latih model dari semua training example yang terkumpul, return metrics."""
    try:
        metadata = service.train()
    except ValueError as e:
        raise ValidationException(str(e))
    return metadata


@router.get("/training/dashboard")
def training_dashboard(request: Request, service: TrainingStatsService = Depends(...)):
    """Halaman ringkasan data training + tombol Train Model."""
    stats = service.get_stats()  # jumlah per label_source, metadata model terakhir jika ada
    return templates.TemplateResponse("training_dashboard.html", {"request": request, **stats})
```

Training dijalankan **sinkron** (bukan background thread) — beda dari proses
video, training model dari ratusan baris data ringan (biasanya selesai dalam
hitungan detik), jadi tidak perlu pola polling seperti job video.

### Halaman `training_dashboard.html`

Tampilkan:
- Jumlah training example per `label_source` (real_performance / user_liked / auto_rejected)
- Tombol besar "Train Model"
- Setelah training selesai: `val_mae`, `val_r2`, dan tabel `feature_importance`
  (urutkan descending) — ini berguna untuk Anda cek: apakah `voice_emotion`/
  `face_emotion` (yang tadinya kalah dari LLM) sekarang punya kontribusi nyata
  ke prediksi model, atau ternyata tidak berpengaruh signifikan.

## Task 5 — Dependency Baru

Tambahkan ke `requirements.txt`:

```
scikit-learn>=1.5
joblib>=1.4
```

## Definisi Selesai

- `data/models/score_model.pkl` dan `data/models/model_metadata.json` berhasil
  dibuat setelah klik "Train Model" (dengan data training minimal 20 row —
  kombinasi 100+ clip Anda + auto-harvest + like manual dari TrainingClip 1-2).
- `training_dashboard.html` menampilkan jumlah training example per
  label_source dan metrics setelah training.
- Training gagal dengan pesan jelas (bukan error 500 mentah) kalau data
  training kurang dari 20 row.
- `feature_importance` di metadata terlihat masuk akal (bukan semua nol/sama).
