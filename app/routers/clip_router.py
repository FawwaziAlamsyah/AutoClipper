"""Generate final clip endpoints."""

import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates  # noqa: F401 (ke AppTemplates)
from app.core.jinja import AppTemplates

from app.core.di.dependencies import get_candidate_service, get_clip_editor_service, get_clip_service
from app.schemas.clip_schema import ClipGenerateRequest
from app.services.candidate_service import CandidateService
from app.services.clip_editor_service import ClipEditorService
from app.services.clip_service import ClipService

router = APIRouter(prefix="/clips", tags=["clips"])
templates = AppTemplates(directory="app/templates")


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


@router.post("/{clip_id}/edit/text", response_class=HTMLResponse)
def edit_add_text(
    request: Request,
    clip_id: int,
    text: str = Form(...),
    position: str = Form("bottom"),
    font_size: int = Form(48),
    color: str = Form("white"),
    service: ClipEditorService = Depends(get_clip_editor_service),
):
    clip = service.add_text(clip_id, text, position, font_size, color)
    return templates.TemplateResponse(
        request=request, name="_clip_edit_preview.html", context={"request": request, "clip": clip, "ts": int(time.time())},
    )


@router.post("/{clip_id}/edit/crop", response_class=HTMLResponse)
def edit_crop(
    request: Request,
    clip_id: int,
    start_time: float = Form(...),
    end_time: float = Form(...),
    service: ClipEditorService = Depends(get_clip_editor_service),
):
    clip = service.crop(clip_id, start_time, end_time)
    return templates.TemplateResponse(
        request=request, name="_clip_edit_preview.html", context={"request": request, "clip": clip, "ts": int(time.time())},
    )


@router.post("/{clip_id}/edit/sound", response_class=HTMLResponse)
async def edit_mix_sound(
    request: Request,
    clip_id: int,
    audio_file: UploadFile = File(...),
    audio_start: float = Form(0.0),
    duck_volume: float = Form(0.3),
    audio_volume: float = Form(1.0),
    video_volume: float = Form(1.0),
    service: ClipEditorService = Depends(get_clip_editor_service),
):
    # Simpan upload audio ke temp dulu sebelum diproses FFmpeg
    temp_dir = Path("data/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_audio_path = temp_dir / f"upload_{clip_id}_{audio_file.filename}"
    with open(temp_audio_path, "wb") as f:
        f.write(await audio_file.read())

    try:
        clip = service.mix_sound(clip_id, str(temp_audio_path), audio_start, video_volume, duck_volume, audio_volume)
    finally:
        temp_audio_path.unlink(missing_ok=True)

    return templates.TemplateResponse(
        request=request, name="_clip_edit_preview.html", context={"request": request, "clip": clip, "ts": int(time.time())},
    )


@router.post("/{clip_id}/edit/volume", response_class=HTMLResponse)
def edit_adjust_volume(
    request: Request,
    clip_id: int,
    video_volume: float = Form(...),
    service: ClipEditorService = Depends(get_clip_editor_service),
):
    clip = service.adjust_volume(clip_id, video_volume)
    return templates.TemplateResponse(
        request=request, name="_clip_edit_preview.html", context={"request": request, "clip": clip, "ts": int(time.time())},
    )


# In-memory progress store: {clip_id: {"pct": 0-100, "done": bool, "error": str|None}}
_edit_progress: dict[int, dict] = {}


@router.get("/{clip_id}/edit/progress")
def edit_progress(clip_id: int):
    """Poll endpoint — return JSON progress untuk edit yang sedang berjalan."""
    from fastapi.responses import JSONResponse
    state = _edit_progress.get(clip_id, {"pct": 0, "done": True, "error": None})
    return JSONResponse(state)


@router.post("/{clip_id}/edit/reset", response_class=HTMLResponse)
def edit_reset(
    request: Request,
    clip_id: int,
    service: ClipEditorService = Depends(get_clip_editor_service),
):
    clip = service.reset(clip_id)
    return templates.TemplateResponse(
        request=request, name="_clip_edit_preview.html", context={"request": request, "clip": clip, "ts": int(time.time())},
    )
