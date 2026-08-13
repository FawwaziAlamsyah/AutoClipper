"""FastAPI application entrypoint.

Menjalankan: uvicorn app.main:app --reload
"""

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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
from app.routers import health_router, video_router, history_router, transcript_router, candidate_router, clip_router, preview_router, subtitle_router, job_router
from app.routers import training_router
from app.routers import storage_router

setup_logging()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

register_exception_handlers(app)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/data/uploads", StaticFiles(directory="data/uploads"), name="uploads")
app.mount("/data/outputs", StaticFiles(directory="data/outputs"), name="outputs")
templates = Jinja2Templates(directory="app/templates")

app.include_router(health_router.router)
app.include_router(video_router.router)
app.include_router(history_router.router)
app.include_router(transcript_router.router)
app.include_router(candidate_router.router)
app.include_router(clip_router.router)
app.include_router(preview_router.router)
app.include_router(subtitle_router.router)
app.include_router(job_router.router)
app.include_router(training_router.router)
app.include_router(storage_router.router)


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
    recent_history = dashboard_service.get_recent_history()

    return render(
        request,
        templates,
        partial_name="dashboard_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "stats": stats,
            "recent_history": recent_history,
        },
    )


if __name__ == "__main__":
    import uvicorn

    # access_log=False: matikan access log per-request agar terminal fokus
    # pada log.debug process. Setara --no-access-log di CLI.
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
