"""Video upload & management endpoints."""

import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.di.dependencies import (
    get_download_service,
    get_job_service,
    get_process_service,
    get_video_service,
)
from app.core.exceptions.base import ValidationException
from app.schemas.video_schema import VideoDetail, VideoUploadResponse, VideoDownloadRequest
from app.schemas.process_schema import ProcessRequest
from app.services.video_service import VideoService
from app.services.download_service import DownloadService
from app.services.process_service import ProcessService
from app.services.job_service import JobService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def upload_page(
    request: Request,
    service: VideoService = Depends(get_video_service),
    job_service: JobService = Depends(get_job_service),
) -> HTMLResponse:
    """Render the upload page."""
    running_jobs = job_service.get_running_by_video()
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
    service: VideoService = Depends(get_video_service),
) -> VideoUploadResponse:
    """Upload a video file."""
    file_bytes = await file.read()
    video = service.upload(file.filename or "unknown.mp4", file_bytes)
    return VideoUploadResponse.model_validate(video)


@router.post("/begin", response_model=VideoUploadResponse)
def begin_upload(
    filename: str,
    service: VideoService = Depends(get_video_service),
) -> VideoUploadResponse:
    """Create an uploading record (survives page navigation)."""
    video = service.begin_upload(filename)
    return VideoUploadResponse.model_validate(video)


@router.post("/{video_id}/finish", response_model=VideoUploadResponse)
def finish_upload(
    video_id: int,
    file: UploadFile = File(...),
    service: VideoService = Depends(get_video_service),
) -> VideoUploadResponse:
    """Stream the uploaded file to disk for a pending upload record.

    Sync (not async) — FastAPI menjalankan ini di threadpool, jadi copyfileobj
    tidak memblokir event loop dan request lain (polling) tetap jalan.
    """
    video = service.finish_upload(video_id, file.file)
    return VideoUploadResponse.model_validate(video)


@router.get("/videos", response_model=list[VideoDetail])
def list_videos(service: VideoService = Depends(get_video_service)) -> list[VideoDetail]:
    """List all uploaded videos."""
    return [VideoDetail.model_validate(v) for v in service.list_all()]


@router.get("/videos/{video_id}", response_model=VideoDetail)
def get_video(
    video_id: int, service: VideoService = Depends(get_video_service)
) -> VideoDetail:
    """Get a single video by ID."""
    return VideoDetail.model_validate(service.get(video_id))


@router.delete("/videos/{video_id}")
def delete_video(
    video_id: int, service: VideoService = Depends(get_video_service)
) -> dict:
    """Delete a video."""
    service.delete(video_id)
    return {"detail": "Video deleted"}


@router.post("/download")
def download_video(
    req: VideoDownloadRequest,
    service: DownloadService = Depends(get_download_service),
) -> dict:
    """Mulai download video dari URL di background; return download_id untuk polling."""
    return service.start_download(req.url)


@router.get("/download/{download_id}")
def get_download_progress(
    download_id: str,
    service: DownloadService = Depends(get_download_service),
) -> dict:
    """Baca progress download aktif (persen, status, video saat selesai)."""
    return service.get_download_progress(download_id)


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
    service: ProcessService = Depends(get_process_service),
) -> dict:
    """Start background processing and return job_id immediately."""
    import threading

    if req is None:
        req = ProcessRequest()

    job_id = service.create_job(video_id)
    thread = threading.Thread(target=_run_process, args=(video_id, job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "running"}


def _run_training_process(video_id: int, job_id: int, actual_score: float) -> None:
    """Run training_ingest pipeline in background thread with its own DB session."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        service = ProcessService(db)
        service.process_video(
            video_id,
            job_id=job_id,
            num_clips=1,
            actual_score=actual_score,
        )
    except Exception as e:
        logger.error("Background training process failed: %s", e, exc_info=e)
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


@router.post("/videos/{video_id}/process-training")
def process_training_clip(
    video_id: int,
    actual_score: float,
    service: ProcessService = Depends(get_process_service),
) -> dict:
    """Proses video sebagai training clip: whole-clip mode, langsung diberi label.

    Dipakai untuk SATU clip contoh yang sudah dilabel manual (dari views/likes).
    Untuk banyak clip sekaligus, lihat TrainingClip 2 (bulk CSV import).
    """
    import threading

    if not (0 <= actual_score <= 10):
        raise ValidationException("actual_score harus antara 0-10")

    job_id = service.create_job(video_id, job_type="training_ingest")
    thread = threading.Thread(
        target=_run_training_process,
        args=(video_id, job_id, actual_score),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "status": "running"}
