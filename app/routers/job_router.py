"""Job status endpoints (for async progress polling)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.di.dependencies import get_job_service
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/active")
def get_active_jobs(service: JobService = Depends(get_job_service)) -> dict:
    """Return all active (pending/running) jobs for global navbar indicator."""
    active = service.get_active_list()
    return {"active_jobs": active, "count": len(active)}


@router.get("/{job_id}/ui", response_class=HTMLResponse)
def job_detail(
    request: Request,
    job_id: int,
    service: JobService = Depends(get_job_service),
) -> HTMLResponse:
    """Render halaman progress tracker step-by-step untuk satu job."""
    status = service.get_status(job_id)
    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "app_name": settings.APP_NAME,
            "status": status,
            "steps": status["steps"],
        },
    )


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, service: JobService = Depends(get_job_service)) -> dict:
    """Cancel a running job."""
    job = service.cancel(job_id)
    return {"job_id": job.id, "status": job.status}


@router.get("/{job_id}")
def get_job_status(job_id: int, service: JobService = Depends(get_job_service)) -> dict:
    """Return job status with per-step progress."""
    return service.get_status(job_id)
