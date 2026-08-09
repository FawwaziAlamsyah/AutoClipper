"""Score engine: aggregate analyzer scores into weighted final score."""

import logging

from app.core.config.settings import settings
from app.repositories.analysis_result_repository import AnalysisResultRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.job_repository import JobRepository
from app.repositories.video_repository import VideoRepository

logger = logging.getLogger(__name__)


class ScoreEngine:
    """Aggregate and weight scores from various analyzers."""

    def __init__(self, db):
        """Initialize with DB session and repos."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.job_repo = JobRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.candidate_repo = CandidateRepository(db)

    def calculate_for_job(self, job_id: int) -> float:
        """Calculate weighted score for all candidates in a job.

        Weights (configurable via settings):
        - LLM Content: 30%
        - Hook: 10%
        - Story: 15%
        - Voice Emotion: 10%
        - Face Emotion: 8%
        - Gesture: 5%
        - Eye Contact: 3%
        - Scene: 4%
        - Audio: 5%
        - Context: 5%
        - Ending: 5%
        """
        job = self.job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        candidates = self.candidate_repo.get_by_job(job_id)
        if not candidates:
            logger.warning("No candidates found for job %d", job_id)
            return 0.0

        for candidate in candidates:
            breakdown = self._calculate_score_breakdown(job_id, candidate.id)
            final_score = sum(breakdown.values())

            candidate.final_score = final_score
            candidate.score_breakdown = breakdown

        self.db.commit()
        return candidates[0].final_score if candidates else 0.0

    def _calculate_score_breakdown(self, job_id: int, candidate_id: int) -> dict[str, float]:
        """Calculate weighted score components for a candidate."""
        analysis = self.analysis_repo.get_by_job(job_id)

        weights = {
            "llm_content": settings.SCORE_WEIGHT_LLM_CONTENT,
            "hook": settings.SCORE_WEIGHT_HOOK,
            "story": settings.SCORE_WEIGHT_STORY,
            "voice_emotion": settings.SCORE_WEIGHT_VOICE_EMOTION,
            "face_emotion": settings.SCORE_WEIGHT_FACE_EMOTION,
            "gesture": settings.SCORE_WEIGHT_GESTURE,
            "eye_contact": settings.SCORE_WEIGHT_EYE_CONTACT,
            "scene": settings.SCORE_WEIGHT_SCENE,
            "audio": settings.SCORE_WEIGHT_AUDIO,
            "context": settings.SCORE_WEIGHT_CONTEXT,
            "ending": settings.SCORE_WEIGHT_ENDING,
        }

        breakdown = {}
        for analyzer_type, weight in weights.items():
            score = self._get_analyzer_score(analysis, analyzer_type)
            breakdown[analyzer_type] = score * weight

        # Penalty for skip keywords (simplified: subtract 0.5 per keyword match)
        penalty = self._calculate_penalty(analysis)
        if penalty > 0:
            breakdown["penalty"] = -abs(penalty)

        return breakdown

    def _get_analyzer_score(self, analysis: list, analyzer_type: str) -> float:
        """Extract average score from analyzer results."""
        results = [a for a in analysis if a.analyzer_type == analyzer_type]
        if not results:
            return 0.5  # Default neutral score

        return sum(r.score or 0 for r in results) / len(results)

    def _calculate_penalty(self, analysis: list) -> float:
        """Calculate penalty for skip keywords."""
        penalties = {
            "sponsor": 0.5,
            "intro": 0.5,
            "outro": 0.5,
            "cta": 0.3,
            "dead air": 0.2,
            "silence": 0.2,
        }

        total_penalty = 0.0
        for a in analysis:
            result_data = a.result_data or {}
            if "keyword" in result_data:
                for kw, val in penalties.items():
                    if kw in result_data["keyword"].lower():
                        total_penalty += val

        return total_penalty
