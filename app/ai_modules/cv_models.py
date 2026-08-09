"""Download & cache model .tflite untuk MediaPipe Tasks API.

MediaPipe wheel py3.14 tak ship model — harus di-download runtime sekali
ke data/models/ lalu di-cache. URL model resmi dari Google storage.
"""

import logging
import urllib.request
from pathlib import Path

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

MODELS = {
    "face_landmarker": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
    "hand_landmarker": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
}

_model_dir = None


def ensure_model(name: str) -> Path:
    """Return path ke model .tflite, download ke data/models/ kalau belum ada.

    Idempoten — file yang sudah ada tidak di-download ulang.
    """
    global _model_dir
    url = MODELS.get(name)
    if url is None:
        raise ValueError(f"Model '{name}' tidak dikenal")

    if _model_dir is None:
        _model_dir = settings.DATA_DIR / "models"
    _model_dir.mkdir(parents=True, exist_ok=True)

    path = _model_dir / f"{name}.task"
    if path.exists() and path.stat().st_size > 0:
        return path

    logger.info("Downloading model %s dari %s", name, url)
    urllib.request.urlretrieve(url, path)  # noqa: S310 — URL model resmi fixed
    logger.info("Model %s tersimpan di %s", name, path)
    return path
