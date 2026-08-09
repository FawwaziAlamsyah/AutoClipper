"""Candidate clip API and UI endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.exceptions.base import NotFoundException
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
    """Render candidates table. Show Open link if a clip already exists."""
    candidates = service.list_latest(limit=100)
    clip_by_candidate = service.get_completed_clips([c.id for c in candidates])

    return templates.TemplateResponse(
        request=request,
        name="candidates.html",
        context={
            "app_name": settings.APP_NAME,
            "candidates": candidates,
            "clip_by_candidate": clip_by_candidate,
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

    return templates.TemplateResponse(
        request=request,
        name="candidate_detail.html",
        context={
            "app_name": settings.APP_NAME,
            "candidate": candidate,
            "breakdown": candidate.score_breakdown or {},
            "clip": clip,
            "preview": preview,
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


@router.delete("/{candidate_id}")
def delete_candidate(
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
) -> dict:
    """Delete a candidate beserta clip terkait."""
    try:
        service.delete_candidate(candidate_id)
    except ValueError:
        raise NotFoundException(f"Candidate {candidate_id} tidak ditemukan")
    return {"detail": "Candidate deleted"}


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
