"""Load model scoring terlatih PER KATEGORI dan sediakan fungsi prediksi."""

import logging
from pathlib import Path

import joblib

from app.ml.feature_builder import build_feature_vector

logger = logging.getLogger(__name__)

# Cache per kategori: {category_id: (model, mtime)}
_model_cache: dict[int, tuple] = {}


def _model_path(category_id: int) -> Path:
    return Path(f"data/models/category_{category_id}/score_model.pkl")


def _load_model(category_id: int):
    """Load model kategori tertentu, reload otomatis kalau file berubah."""
    path = _model_path(category_id)
    if not path.exists():
        return None

    current_mtime = path.stat().st_mtime
    cached = _model_cache.get(category_id)
    if cached is None or cached[1] != current_mtime:
        model = joblib.load(path)
        # Proteksi kualitas model: tolak degenerate model yang seluruh feature_importances_ bernilai 0
        import numpy as np
        if hasattr(model, "feature_importances_"):
            imp = getattr(model, "feature_importances_", None)
            if imp is not None and len(imp) > 0 and np.all(np.array(imp) == 0.0):
                logger.warning(
                    "Score model kategori %d adalah degenerate model (seluruh feature importance bernilai 0.0). "
                    "Model diabaikan dan sistem otomatis fallback ke weighted-sum viral trio.",
                    category_id,
                )
                return None
        _model_cache[category_id] = (model, current_mtime)
        logger.info("Score model kategori %d dimuat ulang dari %s", category_id, path)
        return model
    return cached[0]


def predict_score(analysis_results: list, category_id: int | None) -> float | None:
    """Prediksi skor 0-10 pakai model kategori tertentu.

    None kalau category_id kosong (user tidak pilih kategori) ATAU model
    kategori itu belum pernah dilatih — caller (score_engine) fallback ke
    weighted-sum, sudah ada mekanismenya, tidak perlu diubah.
    """
    if category_id is None:
        return None
    model = _load_model(category_id)
    if model is None:
        return None
    try:
        vector = build_feature_vector(analysis_results)
        prediction = model.predict([vector])[0]
        return max(0.0, min(10.0, float(prediction)))
    except Exception as e:
        logger.warning("Prediksi model kategori %d gagal, fallback ke weighted-sum: %s", category_id, e)
        return None
