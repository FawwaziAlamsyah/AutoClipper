"""Job status endpoints (for async progress polling)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates  # noqa: F401 (ke AppTemplates)
from app.core.jinja import AppTemplates

from app.core.config.settings import settings
from app.core.di.dependencies import get_job_service
from app.core.htmx import render
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = AppTemplates(directory="app/templates")


@router.get("/active")
def get_active_jobs(service: JobService = Depends(get_job_service)) -> dict:
    """Return all active (pending/running) jobs for global navbar indicator."""
    active = service.get_active_list()
    return {"active_jobs": active, "count": len(active)}


@router.get("/active/status-widget", response_class=HTMLResponse)
def active_jobs_widget(
    request: Request,
    service: JobService = Depends(get_job_service),
) -> HTMLResponse:
    """Partial kecil: daftar job yang sedang berjalan, dipoll widget global."""
    active_jobs = service.get_active_list()
    return templates.TemplateResponse(
        request=request,
        name="_active_jobs_widget.html",
        context={"request": request, "active_jobs": active_jobs},
    )


@router.get("/{job_id}/status-fragment", response_class=HTMLResponse)
def job_status_fragment(
    request: Request,
    job_id: int,
    service: JobService = Depends(get_job_service),
) -> HTMLResponse:
    """Fragment untuk progress bar polling — return hanya HTML progress bar + status badges."""
    status = service.get_status(job_id)
    return templates.TemplateResponse(
        request=request,
        name="_job_progress_fragment.html",
        context={
            "status": status,
            "steps": status["steps"],
        },
    )


@router.get("/{job_id}/ui", response_class=HTMLResponse)
def job_detail(
    request: Request,
    job_id: int,
    service: JobService = Depends(get_job_service),
) -> HTMLResponse:
    """Render halaman progress tracker step-by-step untuk satu job."""
    status = service.get_status(job_id)
    return render(
        request,
        templates,
        partial_name="job_detail_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "status": status,
            "steps": status["steps"],
        },
    )


@router.post("/{job_id}/cancel")
def cancel_job(
    request: Request,
    job_id: int,
    service: JobService = Depends(get_job_service),
):
    """Cancel a running job."""
    job = service.cancel(job_id)

    # Return updated partial for htmx, JSON for API
    if request.headers.get("HX-Request"):
        status = service.get_status(job_id)
        return templates.TemplateResponse(
            request=request,
            name="job_detail_content.html",
            context={
                "request": request,
                "app_name": settings.APP_NAME,
                "status": status,
                "steps": status["steps"],
            },
        )
    return {"job_id": job.id, "status": job.status}


@router.get("/{job_id}")
def get_job_status(job_id: int, service: JobService = Depends(get_job_service)) -> dict:
    """Return job status with per-step progress."""
    return service.get_status(job_id)
