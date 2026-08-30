"""Dependency providers used with FastAPI's Depends().

Router tidak pernah instansiasi Service secara langsung — selalu lewat
provider di sini, agar mudah diganti dengan mock saat testing.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.tiktok_account_repository import TikTokAccountRepository
from app.services.candidate_service import CandidateService
from app.services.category_service import CategoryService
from app.services.clip_editor_service import ClipEditorService
from app.services.clip_service import ClipService
from app.services.dashboard_service import DashboardService
from app.services.download_service import DownloadService
from app.services.health_service import HealthService
from app.services.history_service import HistoryService
from app.services.job_service import JobService
from app.services.preview_service import PreviewService
from app.services.process_service import ProcessService
from app.services.subtitle_service import SubtitleService
from app.services.tiktok_auth_service import TikTokAuthService
from app.services.tiktok_upload_service import TikTokUploadService
from app.services.transcript_service import TranscriptService
from app.services.video_service import VideoService


def get_health_service() -> HealthService:
    """Provide a HealthService instance."""
    return HealthService()


def get_video_service(db: Session = Depends(get_db)) -> VideoService:
    return VideoService(db)


def get_download_service(db: Session = Depends(get_db)) -> DownloadService:
    return DownloadService(db)


def get_process_service(db: Session = Depends(get_db)) -> ProcessService:
    return ProcessService(db)


def get_job_service(db: Session = Depends(get_db)) -> JobService:
    return JobService(db)


def get_history_service(db: Session = Depends(get_db)) -> HistoryService:
    return HistoryService(db)


def get_dashboard_service(db: Session = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


def get_transcript_service(db: Session = Depends(get_db)) -> TranscriptService:
    return TranscriptService(db)


def get_candidate_service(db: Session = Depends(get_db)) -> CandidateService:
    return CandidateService(db)


def get_category_service(db: Session = Depends(get_db)) -> CategoryService:
    return CategoryService(db)


def get_clip_service(db: Session = Depends(get_db)) -> ClipService:
    return ClipService(db)


def get_clip_editor_service(db: Session = Depends(get_db)) -> ClipEditorService:
    return ClipEditorService(db)


def get_preview_service(db: Session = Depends(get_db)) -> PreviewService:
    return PreviewService(db)


def get_subtitle_service(db: Session = Depends(get_db)) -> SubtitleService:
    return SubtitleService(db)


def get_training_import_service(db: Session = Depends(get_db)):
    from app.services.training_import_service import TrainingImportService
    return TrainingImportService(db)


def get_training_stats_service(db: Session = Depends(get_db)):
    from app.services.training_stats_service import TrainingStatsService
    return TrainingStatsService(db)


def get_model_trainer(db: Session = Depends(get_db)):
    from app.ml.trainer import ModelTrainer
    return ModelTrainer(db)


def get_training_run_repo(db: Session = Depends(get_db)):
    from app.repositories.training_run_repository import TrainingRunRepository
    return TrainingRunRepository(db)


def get_storage_service(db: Session = Depends(get_db)):
    from app.services.storage_service import StorageService
    return StorageService(db)


def get_tiktok_auth_service(db: Session = Depends(get_db)) -> TikTokAuthService:
    return TikTokAuthService(db)


def get_tiktok_account_repo(db: Session = Depends(get_db)) -> TikTokAccountRepository:
    return TikTokAccountRepository(db)


def get_tiktok_upload_service(db: Session = Depends(get_db)) -> TikTokUploadService:
    return TikTokUploadService(db)
