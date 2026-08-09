"""Candidate clip generation service."""

import logging
from datetime import datetime, UTC

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.models.candidate_model import Candidate
from app.models.job_model import Job
from app.models.video_model import Video
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.job_repository import JobRepository
from app.repositories.video_repository import VideoRepository
from app.models.clip_model import Clip
from app.services.score_engine import ScoreEngine

logger = logging.getLogger(__name__)


class CandidateService:
    """Generate candidate clips from scored segments."""

    def __init__(self, db: Session) -> None:
        """Initialize with DB session."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.job_repo = JobRepository(db)
        self.candidate_repo = CandidateRepository(db)
        self.score_engine = ScoreEngine(db)

    def generate_candidates(self, job_id: int, num_clips: int = 5) -> list[Candidate]:
        """Generate top-N candidate clips based on scores.

        Returns list of candidates with:
        - start_time, end_time
        - final_score
        - hook_text (if any)
        - status: 'candidate'
        """
        job = self.job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        video = self.video_repo.get(job.video_id)
        if video is None:
            raise ValueError(f"Video {job.video_id} not found")

        # Run score engine to populate candidate scores
        self.score_engine.calculate_for_job(job_id)

        # Get candidates ordered by final_score descending
        candidates = self.candidate_repo.get_by_job(job_id)

        # Limit to num_clips
        candidates = candidates[:num_clips]

        logger.info("Generated %d candidates for job %d", len(candidates), job_id)
        return candidates

    def get_candidates(self, job_id: int, limit: int = 10) -> list[Candidate]:
        """Get candidates for a job."""
        return self.candidate_repo.get_by_job(job_id)[:limit]

    def list_latest(self, limit: int = 100) -> list[Candidate]:
        """Return most recent candidates across all videos."""
        return list(
            self.db.query(Candidate).order_by(Candidate.id.desc()).limit(limit).all()
        )

    def get_completed_clips(self, candidate_ids: list[int]) -> dict[int, Clip]:
        """Map candidate_id -> completed clip for the given candidates."""
        if not candidate_ids:
            return {}
        clips = self.db.query(Clip).filter(
            Clip.candidate_id.in_(candidate_ids),
            Clip.status == "completed",
        ).all()
        return {clip.candidate_id: clip for clip in clips}

    def select_candidate(self, candidate_id: int) -> Candidate:
        """Mark a candidate as selected for clipping."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        candidate.status = "selected"
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def reject_candidate(self, candidate_id: int) -> Candidate:
        """Mark a candidate as rejected."""
        candidate = self.candidate_repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        candidate.status = "rejected"
        self.db.commit()
        self.db.refresh(candidate)
        return candidate
