"""Persist Score Engine blend weights (trained vs fallback).

User bisa mengubah rasio campuran final score untuk kategori yang SUDAH dilatih
lewat menu Settings → "Trained category weight". Nilai disimpan sebagai file
JSON kecil (data/score_blend.json) — global, bukan per-session, karena
ScoreEngine dipakai di background pipeline (tidak punya request/cookie).

ScoreEngine membaca nilai di sini; kalau file belum ada / korup, jatuh ke
nilai default dari settings (.env / Settings).
"""

import json
import logging
from pathlib import Path

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

_BLEND_FILE = Path("data/score_blend.json")


def _defaults() -> dict:
    return {
        "trained_weight": settings.SCORE_TRAINED_WEIGHT,
        "fallback_weight": settings.SCORE_FALLBACK_WEIGHT,
    }


def get_blend() -> dict:
    """Baca rasio campuran terakhir. Return default kalau file belum ada."""
    default = _defaults()
    try:
        data = json.loads(_BLEND_FILE.read_text(encoding="utf-8"))
        merged = dict(default)
        merged.update({k: v for k, v in data.items() if k in merged})
        return merged
    except Exception:
        return default


def get_trained_weight() -> float:
    return float(get_blend()["trained_weight"])


def get_fallback_weight() -> float:
    return float(get_blend()["fallback_weight"])


def save_blend(trained_weight: float, fallback_weight: float) -> None:
    """Simpan rasio campuran ke file. Validasi rentang 0.0–1.0 & total ≈ 1."""
    trained = max(0.0, min(1.0, float(trained_weight)))
    fallback = max(0.0, min(1.0, float(fallback_weight)))
    _BLEND_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BLEND_FILE.write_text(
        json.dumps({"trained_weight": trained, "fallback_weight": fallback}),
        encoding="utf-8",
    )
    logger.info("Score blend disimpan: trained=%.2f, fallback=%.2f", trained, fallback)