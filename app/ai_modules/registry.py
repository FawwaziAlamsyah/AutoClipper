"""Registry analyzer aktif.

Satu-satunya tempat mendaftarkan analyzer. Pipeline (analysis_service,
transcript_service) memanggil `get_analyzer(type)` — menambah analyzer baru
berarti daftarkan di sini, orchestration tidak berubah.
"""

import logging

from app.ai_modules.base.analyzer_interface import AnalyzerInterface

logger = logging.getLogger(__name__)

ANALYZER_REGISTRY: dict[str, type[AnalyzerInterface]] = {}


def register_analyzer(cls: type[AnalyzerInterface]) -> type[AnalyzerInterface]:
    """Dekorator: daftarkan class analyzer ke registry berdasarkan analyzer_type."""
    if not cls.analyzer_type:
        raise ValueError(f"Analyzer {cls.__name__} must define analyzer_type")
    ANALYZER_REGISTRY[cls.analyzer_type] = cls
    logger.info("Registered analyzer: %s", cls.analyzer_type)
    return cls


def get_analyzer(analyzer_type: str) -> AnalyzerInterface | None:
    """Return instance analyzer untuk type, atau None jika tidak terdaftar."""
    cls = ANALYZER_REGISTRY.get(analyzer_type)
    if cls is None:
        return None
    try:
        return cls()
    except Exception as e:
        logger.warning("Failed to instantiate analyzer %s: %s", analyzer_type, e)
        return None
