"""Repository for Candidate model."""

from app.models.candidate_model import Candidate
from app.repositories.base_repository import PostgresRepository


class CandidateRepository(PostgresRepository[Candidate]):
    """PostgreSQL repository for candidates."""

    model_class = Candidate

    def get_by_job(self, job_id: int) -> list[Candidate]:
        """Get all candidates for a job, ordered by score descending."""
        return list(
            self.db.query(Candidate)
            .filter(Candidate.job_id == job_id)
            .order_by(Candidate.final_score.desc())
            .all()
        )

    def update_status(self, candidate_id: int, status: str) -> Candidate | None:
        """Update candidate status (candidate/selected/rejected)."""
        candidate = self.get(candidate_id)
        if candidate is None:
            return None
        candidate.status = status
        self.db.commit()
        self.db.refresh(candidate)
        return candidate
