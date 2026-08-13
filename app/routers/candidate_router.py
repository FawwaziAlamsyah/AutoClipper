"""Candidate clip API and UI endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException
from app.core.htmx import render
from app.core.di.dependencies import get_candidate_service, get_preview_service
from app.schemas.candidate_schema import CandidateDetail
from app.services.candidate_service import CandidateService
from app.services.preview_service import PreviewService

router = APIRouter(prefix="/candidates", tags=["candidates"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def candidates_page(
    request: Request,
    service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Render candidates grouped by video — tiap video satu card ringkasan."""
    summaries = service.get_video_summaries()
    return render(
        request,
        templates,
        partial_name="candidates_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "summaries": summaries,
        },
    )


@router.get("/video/{video_id}", response_class=HTMLResponse)
def candidates_by_video(
    request: Request,
    video_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Render tabel candidates untuk satu video."""
    from app.models.video_model import VideoModel
    video = service.db.query(VideoModel).filter(VideoModel.id == video_id).first()
    if video is None:
        raise NotFoundException(f"Video {video_id} tidak ditemukan")

    candidates = service.list_by_video(video_id)
    clip_by_candidate = service.get_completed_clips([c.id for c in candidates])

    # Build plain dicts untuk render — hindari lazy-load issue di Jinja2
    candidate_rows = []
    for c in candidates:
        clip = clip_by_candidate.get(c.id)
        clip_filename = None
        if clip and clip.file_path:
            import os
            clip_filename = os.path.basename(clip.file_path)
        candidate_rows.append({
            "id": c.id,
            "start_time": int(c.start_time),
            "end_time": int(c.end_time),
            "final_score": c.final_score,
            "status": c.status,
            "label_source": c.label_source,
            "actual_score": c.actual_score,
            "job_id": c.job_id,
            "clip_filename": clip_filename,
        })

    return render(
        request,
        templates,
        partial_name="candidates_video_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "video": video,
            "candidates": candidate_rows,
        },
    )


@router.get("/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(
    request: Request,
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
    preview_service: PreviewService = Depends(get_preview_service),
) -> HTMLResponse:
    """Render detail candidate: breakdown score, preview, subtitle form."""
    try:
        candidate = service.get_candidate(candidate_id)
    except ValueError:
        raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")

    clip_by_candidate = service.get_completed_clips([candidate_id])
    clip = clip_by_candidate.get(candidate_id)

    try:
        preview = preview_service.get_candidate_preview(candidate_id)
    except NotFoundException:
        preview = None

    # Map local video path ke static URL yang di-serve oleh app.
    # Path absolute Windows (C:\...\data\uploads\file.mp4) → /data/uploads/file.mp4
    if preview:
        vp = preview.get("video_path", "")
        norm = vp.replace("\\", "/")
        if "data/uploads" in norm:
            preview["video_url"] = "/data/uploads/" + norm.split("data/uploads/", 1)[1].lstrip("/")
        else:
            preview["video_url"] = None

    return render(
        request,
        templates,
        partial_name="candidate_detail_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "candidate": candidate,
            "breakdown": candidate.score_breakdown or {},
            "clip": clip,
            "preview": preview,
            "video_id": candidate.video_id,
        },
    )


@router.post("/jobs/{job_id}", response_model=list[CandidateDetail])
def generate_candidates(
    job_id: int,
    num_clips: int = Query(5, ge=1, le=20),
    service: CandidateService = Depends(get_candidate_service),
) -> list[CandidateDetail]:
    """Generate top-N candidate clips for a job."""
    candidates = service.generate_candidates(job_id, num_clips)
    return [_to_detail(c) for c in candidates]


@router.get("/jobs/{job_id}", response_model=list[CandidateDetail])
def list_candidates(
    job_id: int,
    limit: int = Query(10, ge=1, le=50),
    service: CandidateService = Depends(get_candidate_service),
) -> list[CandidateDetail]:
    """List candidates for a job."""
    candidates = service.get_candidates(job_id, limit)
    return [_to_detail(c) for c in candidates]


@router.patch("/{candidate_id}/select")
def select_candidate(
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> CandidateDetail:
    """Select a candidate for clipping."""
    candidate = service.select_candidate(candidate_id)
    return _to_detail(candidate)


@router.patch("/{candidate_id}/reject")
def reject_candidate(
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> CandidateDetail:
    """Reject a candidate."""
    candidate = service.reject_candidate(candidate_id)
    return _to_detail(candidate)


@router.delete("/{candidate_id}", response_class=HTMLResponse)
def delete_candidate(
    request: Request,
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Delete a candidate beserta clip terkait."""
    try:
        service.delete_candidate(candidate_id)
    except ValueError:
        raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")
    return HTMLResponse("")  # Return empty HTML — htmx swap=outerHTML akan menghapus <tr> dari DOM


@router.post("/{candidate_id}/like", response_class=HTMLResponse)
def like_candidate(
    request: Request,
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Tandai candidate sebagai contoh bagus untuk training (dari review manual)."""
    try:
        candidate = service.mark_as_liked(candidate_id)
    except ValueError:
        raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")
    return templates.TemplateResponse(
        request=request,
        name="_like_button.html",
        context={"request": request, "candidate": candidate},
    )


@router.post("/{candidate_id}/unlike", response_class=HTMLResponse)
def unlike_candidate(
    request: Request,
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Batalkan status liked (jaga-jaga salah klik meski sudah ada konfirmasi)."""
    try:
        candidate = service.unmark_liked(candidate_id)
    except ValueError:
        raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")
    return templates.TemplateResponse(
        request=request,
        name="_like_button.html",
        context={"request": request, "candidate": candidate},
    )


@router.post("/{candidate_id}/dislike", response_class=HTMLResponse)
def dislike_candidate(
    request: Request,
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Tandai candidate sebagai contoh JELEK untuk training (dari review manual)."""
    try:
        candidate = service.mark_as_disliked(candidate_id)
    except ValueError:
        raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")
    return templates.TemplateResponse(
        request=request,
        name="_like_button.html",
        context={"request": request, "candidate": candidate},
    )


@router.post("/{candidate_id}/undislike", response_class=HTMLResponse)
def undislike_candidate(
    request: Request,
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> HTMLResponse:
    """Batalkan status disliked."""
    try:
        candidate = service.unmark_disliked(candidate_id)
    except ValueError:
        raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")
    return templates.TemplateResponse(
        request=request,
        name="_like_button.html",
        context={"request": request, "candidate": candidate},
    )


def _to_detail(c) -> CandidateDetail:
    """Map ORM candidate to response schema."""
    return CandidateDetail(
        id=c.id,
        video_id=c.video_id,
        job_id=c.job_id,
        start_time=c.start_time,
        end_time=c.end_time,
        final_score=c.final_score,
        score_breakdown=c.score_breakdown or {},
        hook_text=c.hook_text,
        status=c.status,
        created_at=c.created_at,
    )
