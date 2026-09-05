"""FastAPI application entrypoint.

Menjalankan: uvicorn app.main:app --reload
"""

# ── Disable MediaPipe / TF / GLOG telemetry & verbose log SEBELUM import lain ──
# Harus di sini (bukan di whisper_analyzer._load_model) karena mediapipe di-import
# di level modul oleh gesture_analyzer, face_emotion_analyzer, eye_contact_analyzer
# — semuanya masuk registry saat startup, jauh sebelum Whisper sempat di-load.
import os
os.environ.setdefault("MEDIAPIPE_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("GLOG_minloglevel", "3")
# ────────────────────────────────────────────────────────────────────────────────

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates  # noqa: F401 (ke AppTemplates)
from app.core.jinja import AppTemplates

from app.core.config.settings import settings
from app.core.di.dependencies import get_dashboard_service
from app.core.exceptions.handlers import register_exception_handlers
from app.core.htmx import render
from app.core.logging.logger import setup_logging
import logging

logger = logging.getLogger(__name__)
from app.db.session import SessionLocal
from app.services.dashboard_service import DashboardService
from app.services.job_service import JobService
from app.services.video_service import VideoService
from app.routers import health_router, video_router, history_router, transcript_router, candidate_router, category_router, clip_router, preview_router, subtitle_router, job_router, legal_router, settings_router
from app.routers import training_router
from app.routers import storage_router
from app.routers import tiktok_router
from app.routers import llm_router

setup_logging()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

register_exception_handlers(app)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/data/uploads", StaticFiles(directory="data/uploads"), name="uploads")
app.mount("/data/outputs", StaticFiles(directory="data/outputs"), name="outputs")
templates = AppTemplates(directory="app/templates")

app.include_router(health_router.router)
app.include_router(video_router.router)
app.include_router(history_router.router)
app.include_router(transcript_router.router)
app.include_router(candidate_router.router)
app.include_router(category_router.router)
app.include_router(clip_router.router)
app.include_router(preview_router.router)
app.include_router(subtitle_router.router)
app.include_router(job_router.router)
app.include_router(legal_router.router)
app.include_router(settings_router.router)
app.include_router(training_router.router)
app.include_router(storage_router.router)
app.include_router(tiktok_router.router)
app.include_router(llm_router.router)


@app.on_event("startup")
def cleanup_stale_jobs() -> None:
    """Mark jobs/videos stuck as failed after a server restart."""
    db = SessionLocal()
    try:
        job_service = JobService(db)
        job_service.mark_stale_failed()
        video_service = VideoService(db)
        video_service.mark_stale_uploading_failed()
    finally:
        db.close()


@app.get("/")
def index(
    request: Request,
    dashboard_service: DashboardService = Depends(get_dashboard_service),
):
    """Render the dashboard."""
    stats = dashboard_service.get_stats()

    return render(
        request,
        templates,
        partial_name="dashboard_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "stats": stats,
        },
    )


if __name__ == "__main__":
    import uvicorn

    # access_log=False: matikan access log per-request agar terminal fokus
    # pada log.debug process. Setara --no-access-log di CLI.
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
