"""Candidate clip API and UI endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.db.session import get_db
from app.models.candidate_model import Candidate
from app.models.clip_model import Clip
from app.schemas.candidate_schema import CandidateDetail
from app.services.candidate_service import CandidateService

router = APIRouter(prefix="/candidates", tags=["candidates"])
templates = Jinja2Templates(directory="app/templates")


def _get_service(db: Session = Depends(get_db)) -> CandidateService:
    return CandidateService(db)


@router.get("", response_class=HTMLResponse)
def candidates_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Render candidates table. Show Open link if a clip already exists."""
    candidates = db.query(Candidate).order_by(Candidate.id.desc()).limit(100).all()

    candidate_ids = [c.id for c in candidates]
    clips = (
        db.query(Clip)
        .filter(Clip.candidate_id.in_(candidate_ids), Clip.status == "completed")
        .all()
        if candidate_ids
        else []
    )
    clip_by_candidate = {clip.candidate_id: clip for clip in clips}

    return templates.TemplateResponse(
        request=request,
        name="candidates.html",
        context={
            "app_name": settings.APP_NAME,
            "candidates": candidates,
            "clip_by_candidate": clip_by_candidate,
        },
    )


@router.post("/jobs/{job_id}", response_model=list[CandidateDetail])
def generate_candidates(
    job_id: int,
    num_clips: int = Query(5, ge=1, le=20),
    service: CandidateService = Depends(_get_service),
) -> list[CandidateDetail]:
    """Generate top-N candidate clips for a job."""
    candidates = service.generate_candidates(job_id, num_clips)
    return [_to_detail(c) for c in candidates]


@router.get("/jobs/{job_id}", response_model=list[CandidateDetail])
def list_candidates(
    job_id: int,
    limit: int = Query(10, ge=1, le=50),
    service: CandidateService = Depends(_get_service),
) -> list[CandidateDetail]:
    """List candidates for a job."""
    candidates = service.get_candidates(job_id, limit)
    return [_to_detail(c) for c in candidates]


@router.patch("/{candidate_id}/select")
def select_candidate(
    candidate_id: int,
    service: CandidateService = Depends(_get_service),
) -> CandidateDetail:
    """Select a candidate for clipping."""
    candidate = service.select_candidate(candidate_id)
    return _to_detail(candidate)


@router.patch("/{candidate_id}/reject")
def reject_candidate(
    candidate_id: int,
    service: CandidateService = Depends(_get_service),
) -> CandidateDetail:
    """Reject a candidate."""
    candidate = service.reject_candidate(candidate_id)
    return _to_detail(candidate)


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
