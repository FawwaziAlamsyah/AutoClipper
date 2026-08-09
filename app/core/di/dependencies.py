"""Dependency providers used with FastAPI's Depends().

Router tidak pernah instansiasi Service secara langsung — selalu lewat
provider di sini, agar mudah diganti dengan mock saat testing.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.analysis_service import AnalysisService
from app.services.candidate_service import CandidateService
from app.services.clip_service import ClipService
from app.services.dashboard_service import DashboardService
from app.services.download_service import DownloadService
from app.services.health_service import HealthService
from app.services.history_service import HistoryService
from app.services.job_service import JobService
from app.services.preview_service import PreviewService
from app.services.process_service import ProcessService
from app.services.subtitle_service import SubtitleService
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


def get_clip_service(db: Session = Depends(get_db)) -> ClipService:
    return ClipService(db)


def get_preview_service(db: Session = Depends(get_db)) -> PreviewService:
    return PreviewService(db)


def get_subtitle_service(db: Session = Depends(get_db)) -> SubtitleService:
    return SubtitleService(db)


def get_analysis_service(db: Session = Depends(get_db)) -> AnalysisService:
    return AnalysisService(db)
