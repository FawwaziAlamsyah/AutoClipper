"""Ringkasan penggunaan disk + daftar video kandidat untuk diarsipkan."""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.video_repository import VideoRepository

logger = logging.getLogger(__name__)


def _dir_size_mb(path: Path) -> float:
    """Total ukuran semua file di satu folder (rekursif), dalam MB."""
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / 1_000_000, 1)


class StorageService:
    """Ringkasan disk usage dan daftar video yang belum diarsipkan."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.candidate_repo = CandidateRepository(db)

    def get_usage_stats(self) -> dict:
        """Ukuran tiap folder data/ — buat lihat mana yang paling makan tempat."""
        return {
            "uploads_mb": _dir_size_mb(settings.UPLOAD_DIR),
            "outputs_mb": _dir_size_mb(settings.OUTPUT_DIR),
            "cache_mb": _dir_size_mb(settings.CACHE_DIR),
            "models_mb": _dir_size_mb(settings.DATA_DIR / "models"),
        }

    def get_archivable_videos(self) -> list[dict]:
        """Video status ready & belum diarsipkan, diurutkan dari file terbesar.

        unrendered_count cuma informasi, bukan penghalang — semua boleh diarsipkan.
        """
        videos = self.video_repo.get_ready_not_archived()
        result = []
        for v in videos:
            size_mb = (
                round(Path(v.file_path).stat().st_size / 1_000_000, 1)
                if v.file_path and Path(v.file_path).exists()
                else 0.0
            )
            result.append({
                "video": v,
                "size_mb": size_mb,
                "unrendered_count": self.candidate_repo.count_unrendered_by_video(v.id),
            })
        return sorted(result, key=lambda r: r["size_mb"], reverse=True)
