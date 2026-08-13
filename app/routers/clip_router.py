"""Generate final clip endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.di.dependencies import get_clip_service, get_candidate_service
from app.schemas.clip_schema import ClipGenerateRequest, ClipDetail
from app.services.clip_service import ClipService
from app.services.candidate_service import CandidateService

router = APIRouter(prefix="/clips", tags=["clips"])
templates = Jinja2Templates(directory="app/templates")


@router.post("", response_class=HTMLResponse)
def generate_clip(
    request: Request,
    req: ClipGenerateRequest,
    service: ClipService = Depends(get_clip_service),
) -> HTMLResponse:
    """Generate a final clip from a candidate using FFmpeg."""
    clip = service.generate_clip(req.candidate_id, req.aspect_ratio, req.subtitle_enabled, req.subtitle_style)
    
    # Return HTML for htmx requests, JSON for API requests
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="_clip_result.html",
            context={
                "request": request,
                "clip": {
                    "file_path": clip.file_path,
                    "id": clip.id
                }
            }
        )
    else:
        # Return JSON for API requests
        from fastapi.responses import JSONResponse
        return JSONResponse({
            "id": clip.id,
            "file_path": clip.file_path,
            "candidate_id": clip.candidate_id,
            "aspect_ratio": clip.aspect_ratio,
            "subtitle_enabled": clip.subtitle_enabled,
            "subtitle_style": clip.subtitle_style,
            "created_at": clip.created_at.isoformat() if clip.created_at else None,
        })


@router.post("/generate-htmx", response_class=HTMLResponse)
def generate_clip_htmx(
    request: Request,
    candidate_id: int = Query(...),
    aspect_ratio: str = Query("16:9"),
    subtitle_enabled: bool = Query(False),
    subtitle_style: str = Query("minimal"),
    service: ClipService = Depends(get_clip_service),
    candidate_service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Generate clip dari htmx — return partial baris tabel candidate."""
    clip = service.generate_clip(candidate_id, aspect_ratio, subtitle_enabled, subtitle_style)
    # Fetch candidate untuk get semua data (include clip_filename)
    candidate_obj = candidate_service.get_candidate(candidate_id)
    clip_by_candidate = candidate_service.get_completed_clips([candidate_id])
    candidate_clip = clip_by_candidate.get(candidate_id)
    
    # Build dict untuk template (sama seperti di candidates_by_video)
    import os
    clip_filename = None
    if candidate_clip and candidate_clip.file_path:
        clip_filename = os.path.basename(candidate_clip.file_path)
    
    candidate_dict = {
        "id": candidate_obj.id,
        "start_time": int(candidate_obj.start_time),
        "end_time": int(candidate_obj.end_time),
        "final_score": candidate_obj.final_score,
        "status": candidate_obj.status,
        "label_source": candidate_obj.label_source,
        "actual_score": candidate_obj.actual_score,
        "job_id": candidate_obj.job_id,
        "clip_filename": clip_filename,
    }
    
    return templates.TemplateResponse(
        request=request,
        name="_candidate_row.html",
        context={"request": request, "candidate": candidate_dict},
    )


@router.post("/generate-detail", response_class=HTMLResponse)
def generate_clip_detail(
    request: Request,
    candidate_id: int = Query(...),
    aspect_ratio: str = Query("16:9"),
    subtitle_enabled: bool = Query(False),
    subtitle_style: str = Query("minimal"),
    service: ClipService = Depends(get_clip_service),
) -> HTMLResponse:
    """Generate clip dan return HTML untuk halaman candidate detail."""
    import os
    clip = service.generate_clip(candidate_id, aspect_ratio, subtitle_enabled, subtitle_style)
    filename = os.path.basename(clip.file_path)
    return templates.TemplateResponse(
        request=request,
        name="_clip_result.html",
        context={
            "request": request,
            "clip": {
                "file_path": clip.file_path,
                "id": clip.id,
                "filename": filename,
            }
        }
    )
