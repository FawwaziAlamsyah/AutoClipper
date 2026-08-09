"""Video upload & management endpoints."""

import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.db.session import get_db
from app.schemas.video_schema import VideoDetail, VideoUploadResponse, VideoDownloadRequest
from app.schemas.process_schema import ProcessRequest
from app.services.video_service import VideoService
from app.services.download_service import DownloadService
from app.services.process_service import ProcessService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])
templates = Jinja2Templates(directory="app/templates")


def _get_service(db: Session = Depends(get_db)) -> VideoService:
    return VideoService(db)


def _get_download_service(db: Session = Depends(get_db)) -> DownloadService:
    return DownloadService(db)


def _get_process_service(db: Session = Depends(get_db)) -> ProcessService:
    return ProcessService(db)


@router.get("", response_class=HTMLResponse)
def upload_page(
    request: Request,
    db: Session = Depends(get_db),
    service: VideoService = Depends(_get_service),
) -> HTMLResponse:
    """Render the upload page."""
    # Jobs yang sedang berjalan, per video: {video_id: {"job_id":..., "current_step":...}}
    from app.models.job_model import Job
    running_jobs: dict[int, dict] = {}
    for j in db.query(Job).filter(Job.status == "running").all():
        running_jobs[j.video_id] = {
            "job_id": j.id,
            "current_step": j.current_step or "running",
        }
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "app_name": settings.APP_NAME,
            "allowed_extensions": settings.ALLOWED_VIDEO_EXTENSIONS,
            "max_size_mb": settings.MAX_UPLOAD_SIZE_MB,
            "videos": service.list_all(),
            "running_jobs": running_jobs,
        },
    )


@router.post("", response_model=VideoUploadResponse)
async def upload_video(
    file: UploadFile = File(...),
    service: VideoService = Depends(_get_service),
) -> VideoUploadResponse:
    """Upload a video file."""
    file_bytes = await file.read()
    video = service.upload(file.filename or "unknown.mp4", file_bytes)
    return VideoUploadResponse.model_validate(video)


@router.get("/videos", response_model=list[VideoDetail])
def list_videos(service: VideoService = Depends(_get_service)) -> list[VideoDetail]:
    """List all uploaded videos."""
    return [VideoDetail.model_validate(v) for v in service.list_all()]


@router.get("/videos/{video_id}", response_model=VideoDetail)
def get_video(
    video_id: int, service: VideoService = Depends(_get_service)
) -> VideoDetail:
    """Get a single video by ID."""
    return VideoDetail.model_validate(service.get(video_id))


@router.delete("/videos/{video_id}")
def delete_video(
    video_id: int, service: VideoService = Depends(_get_service)
) -> dict:
    """Delete a video."""
    service.delete(video_id)
    return {"detail": "Video deleted"}


@router.post("/download", response_model=VideoUploadResponse)
def download_video(
    req: VideoDownloadRequest,
    service: DownloadService = Depends(_get_download_service),
) -> VideoUploadResponse:
    """Download video from URL."""
    video = service.download_video(req.url)
    return VideoUploadResponse.model_validate(video)


def _run_process(video_id: int, job_id: int, req: ProcessRequest) -> None:
    """Run pipeline in background thread with its own DB session."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        service = ProcessService(db)
        service.process_video(
            video_id,
            job_id=job_id,
            num_clips=req.num_clips,
            keywords=req.keyword_boost,
            skip_keywords=req.skip_keywords,
            language=req.language,
            min_duration=req.min_clip_duration,
            max_duration=req.max_clip_duration,
            analyze_start_time=req.analyze_start_time,
            analyze_end_time=req.analyze_end_time,
        )
    except Exception as e:
        logger.error("Background process failed: %s", e, exc_info=e)
        db.rollback()
        service = ProcessService(db)
        job = service.job_service.get(job_id)
        if job.status == "cancelled":
            db.close()
            return
        step = job.current_step or "transcribe"
        service.job_service.finish_step(job_id, step, success=False, error=str(e))
    finally:
        db.close()


@router.post("/videos/{video_id}/process")
def process_video(
    video_id: int,
    req: ProcessRequest | None = None,
    service: ProcessService = Depends(_get_process_service),
) -> dict:
    """Start background processing and return job_id immediately."""
    import threading

    if req is None:
        req = ProcessRequest()

    job_id = service.create_job(video_id)
    thread = threading.Thread(target=_run_process, args=(video_id, job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "running"}
