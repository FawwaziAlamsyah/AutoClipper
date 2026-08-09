"""FastAPI application entrypoint.

Menjalankan: uvicorn app.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.exceptions.handlers import register_exception_handlers
from app.core.logging.logger import setup_logging
import logging

logger = logging.getLogger(__name__)
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.db.session import SessionLocal
from app.services.dashboard_service import DashboardService
from app.services.job_service import JobService
from app.routers import health_router, video_router, history_router, transcript_router, candidate_router, clip_router, preview_router, subtitle_router, job_router

setup_logging()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

app.add_middleware(RequestLoggingMiddleware)
register_exception_handlers(app)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
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


@app.on_event("startup")
def cleanup_stale_jobs() -> None:
    """Mark jobs stuck in running/pending as failed after a server restart."""
    db = SessionLocal()
    try:
        job_service = JobService(db)
        job_service.mark_stale_failed()
    finally:
        db.close()


@app.get("/")
def index(request: Request):
    """Render the dashboard."""
    db = SessionLocal()
    try:
        dashboard_service = DashboardService(db)
        stats = dashboard_service.get_stats()
        recent_history = dashboard_service.get_recent_history()
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"app_name": settings.APP_NAME, "stats": stats, "recent_history": recent_history},
    )
