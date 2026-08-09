"""Transcript API endpoints."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.transcript_schema import TranscriptDetail, TranscriptSegmentDetail
from app.services.transcript_service import TranscriptService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcript", tags=["transcript"])


def _get_service(db: Session = Depends(get_db)) -> TranscriptService:
    return TranscriptService(db)


@router.post("/videos/{video_id}", response_model=TranscriptDetail)
def create_transcript(
    video_id: int,
    language: str | None = Query(None, description="id, en, or omit for auto"),
    force: bool = Query(False, description="Re-run even if cached"),
    job_id: int | None = Query(None),
    service: TranscriptService = Depends(_get_service),
) -> TranscriptDetail:
    """Extract audio + transcribe video. Reuses cache unless force=true."""
    transcript = service.transcribe(video_id, job_id=job_id, language=language, force=force)
    return _to_detail(service, transcript)


@router.get("/videos/{video_id}", response_model=TranscriptDetail)
def get_transcript_by_video(
    video_id: int,
    service: TranscriptService = Depends(_get_service),
) -> TranscriptDetail:
    """Get latest transcript for a video."""
    return _to_detail(service, service.get_by_video(video_id))


@router.get("/jobs/{job_id}", response_model=TranscriptDetail)
def get_transcript_by_job(
    job_id: int,
    service: TranscriptService = Depends(_get_service),
) -> TranscriptDetail:
    """Get transcript for a specific job."""
    return _to_detail(service, service.get_by_job(job_id))


def _to_detail(service: TranscriptService, transcript) -> TranscriptDetail:
    """Map ORM transcript + segments to response schema."""
    segs = service.segment_repo.get_by_transcript(transcript.id)
    return TranscriptDetail(
        id=transcript.id,
        video_id=transcript.video_id,
        job_id=transcript.job_id,
        engine=transcript.engine,
        language=transcript.language,
        full_text=transcript.full_text,
        created_at=transcript.created_at,
        segments=[
            TranscriptSegmentDetail(
                id=s.id,
                start_time=s.start_time,
                end_time=s.end_time,
                text=s.text,
                confidence=s.confidence,
            )
            for s in segs
        ],
    )
