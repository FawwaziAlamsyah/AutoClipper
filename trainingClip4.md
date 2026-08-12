# TrainingClip 4 — Integrasi Model ke Live Scoring

Konteks: model sudah bisa dilatih dan tersimpan di `data/models/score_model.pkl`
(TrainingClip 3). Tahap TERAKHIR ini menyambungkan model itu ke
`score_engine.py` supaya benar-benar dipakai untuk scoring candidate
sungguhan — dengan fallback aman kalau model belum ada/gagal dimuat.

## Task 1 — `app/ml/predictor.py` (Load Model Sekali, Reuse)

```python
"""Load model scoring terlatih dan sediakan fungsi prediksi untuk score_engine."""

import logging
from pathlib import Path

import joblib

from app.ml.feature_builder import build_feature_vector
from app.ml.trainer import MODEL_PATH

logger = logging.getLogger(__name__)

_model = None
_model_mtime: float | None = None


def _load_model():
    """Load model dari disk, reload otomatis kalau file berubah (habis retrain)."""
    global _model, _model_mtime
    if not MODEL_PATH.exists():
        return None

    current_mtime = MODEL_PATH.stat().st_mtime
    if _model is None or current_mtime != _model_mtime:
        _model = joblib.load(MODEL_PATH)
        _model_mtime = current_mtime
        logger.info("Score model dimuat ulang dari %s", MODEL_PATH)
    return _model


def predict_score(analysis_results: list) -> float | None:
    """Prediksi skor 0-10 dari analysis_results satu window. None jika model belum ada."""
    model = _load_model()
    if model is None:
        return None
    try:
        vector = build_feature_vector(analysis_results)
        prediction = model.predict([vector])[0]
        return max(0.0, min(10.0, float(prediction)))
    except Exception as e:
        logger.warning("Prediksi model gagal, fallback ke weighted-sum: %s", e)
        return None
```

## Task 2 — Modifikasi `score_engine.py`

Ubah `_calculate_score_breakdown()` supaya coba model dulu, fallback ke
weighted-sum manual kalau model tidak tersedia atau gagal:

```python
from app.ml.predictor import predict_score

def _calculate_score_breakdown(self, job_id: int, candidate_id: int) -> dict[str, dict]:
    analysis = self.analysis_repo.get_by_job(job_id)
    active_types = {a.analyzer_type for a in analysis}

    # --- Cara lama: weighted-sum manual (tetap dihitung, dipakai sebagai
    # fallback DAN sebagai pembanding transparansi di breakdown) ---
    weights = {
        "llm_content": settings.SCORE_WEIGHT_LLM_CONTENT,
        "hook": settings.SCORE_WEIGHT_HOOK,
        "story": settings.SCORE_WEIGHT_STORY,
        "voice_emotion": settings.SCORE_WEIGHT_VOICE_EMOTION,
        "face_emotion": settings.SCORE_WEIGHT_FACE_EMOTION,
        "gesture": settings.SCORE_WEIGHT_GESTURE,
        "eye_contact": settings.SCORE_WEIGHT_EYE_CONTACT,
        "scene": settings.SCORE_WEIGHT_SCENE,
        "audio": settings.SCORE_WEIGHT_AUDIO,
        "context": settings.SCORE_WEIGHT_CONTEXT,
        "ending": settings.SCORE_WEIGHT_ENDING,
    }
    breakdown = {}
    for analyzer_type, weight in weights.items():
        if weight <= 0 or analyzer_type not in active_types:
            continue
        score = self._get_analyzer_score(analysis, analyzer_type)
        breakdown[analyzer_type] = {
            "score": score, "weight": weight,
            "contribution": round(score * weight, 2),
            "reason": self._get_reason(analysis, analyzer_type),
        }
    penalty = self._calculate_penalty(analysis)
    if penalty > 0:
        breakdown["penalty"] = {
            "score": penalty, "weight": 0.0, "contribution": round(-abs(penalty), 2),
            "reason": self._get_reason(analysis, "penalty") or "Konten spam/CTA terdeteksi",
        }
    legacy_score = sum(v["contribution"] for v in breakdown.values())

    # --- Cara baru: model terlatih, dipakai sebagai final_score kalau tersedia ---
    model_score = None
    if settings.USE_TRAINED_SCORE_MODEL:
        model_score = predict_score(analysis)

    breakdown["_meta"] = {
        "scoring_method": "trained_model" if model_score is not None else "weighted_sum",
        "legacy_weighted_sum_score": round(legacy_score, 2),
        "model_predicted_score": round(model_score, 2) if model_score is not None else None,
    }

    return breakdown


def calculate_for_job(self, job_id: int) -> float:
    job = self.job_repo.get(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    candidates = self.candidate_repo.get_by_job(job_id)
    if not candidates:
        logger.warning("No candidates found for job %d", job_id)
        return 0.0

    for candidate in candidates:
        breakdown = self._calculate_score_breakdown(job_id, candidate.id)
        meta = breakdown["_meta"]
        final_score = (
            meta["model_predicted_score"]
            if meta["scoring_method"] == "trained_model"
            else meta["legacy_weighted_sum_score"]
        )
        candidate.final_score = final_score
        candidate.score_breakdown = breakdown

    self.db.commit()
    return candidates[0].final_score if candidates else 0.0
```

## Task 3 — Setting Toggle & Rollback Aman

Tambahkan di `settings.py`:

```python
USE_TRAINED_SCORE_MODEL: bool = True  # set False untuk paksa pakai weighted-sum lama
```

Kalau suatu saat model hasil training ternyata malah lebih buruk dari
weighted-sum manual (bisa dicek dari hasil klip yang di-generate), tinggal set
`False` di `.env` — sistem otomatis balik ke cara lama tanpa perlu ubah kode.

## Task 4 — Transparansi di UI

Di `candidate_detail.html`, tampilkan info dari `breakdown["_meta"]`:

```html
<div class="alert alert-info small">
  Skor dihitung pakai:
  <strong>{{ "Model terlatih" if breakdown._meta.scoring_method == "trained_model" else "Weighted-sum manual" }}</strong>
  {% if breakdown._meta.model_predicted_score %}
    (model: {{ breakdown._meta.model_predicted_score }},
     weighted-sum lama: {{ breakdown._meta.legacy_weighted_sum_score }})
  {% endif %}
</div>
```

Supaya Anda selalu tahu skor yang dilihat berasal dari mana, dan bisa
membandingkan langsung dua metode selama masa transisi.

## Task 5 — Kapan Harus Retrain

Ini bukan kode, tapi operasional: model **tidak otomatis retrain sendiri**
tiap ada like/reject baru — harus klik manual "Train Model" di
`training_dashboard.html` (TrainingClip 3). Saran: retrain setiap terkumpul
20-30 label baru, bukan tiap 1 like — supaya tiap training pakai data yang
cukup banyak dan hasilnya lebih stabil (tidak "lompat-lompat" tiap kali retrain).

## Definisi Selesai

- Setelah "Train Model" pernah dijalankan minimal sekali, generate candidate
  baru dari video baru → `score_breakdown._meta.scoring_method` = `"trained_model"`.
- Set `USE_TRAINED_SCORE_MODEL=False` di `.env` → scoring balik pakai
  weighted-sum manual, aplikasi tetap jalan normal tanpa error.
- Hapus/pindahkan `data/models/score_model.pkl` secara manual (simulasikan
  model belum pernah dilatih) → scoring otomatis fallback ke weighted-sum
  tanpa crash.
- `candidate_detail.html` menampilkan metode scoring yang dipakai secara jelas.
