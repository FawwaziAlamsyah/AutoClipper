"""Load model scoring terlatih dan sediakan fungsi prediksi untuk score_engine."""

import logging

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
