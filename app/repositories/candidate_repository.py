"""Repository for Candidate model."""

from app.models.candidate_model import CandidateModel
from app.repositories.base_repository import PostgresRepository


class CandidateRepository(PostgresRepository[CandidateModel]):
    """PostgreSQL repository for candidates."""

    model_class = CandidateModel

    def get_by_job(self, job_id: int) -> list[CandidateModel]:
        """Get all candidates for a job, ordered by score descending."""
        return list(
            self.db.query(CandidateModel)
            .filter(CandidateModel.job_id == job_id)
            .order_by(CandidateModel.final_score.desc())
            .all()
        )

    def update_status(self, candidate_id: int, status: str) -> CandidateModel | None:
        """Update candidate status (candidate/selected/rejected)."""
        candidate = self.get(candidate_id)
        if candidate is None:
            return None
        candidate.status = status
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def get_training_examples(self, category_id: int) -> list[CandidateModel]:
        """Get training examples for one category only."""
        return list(
            self.db.query(CandidateModel)
            .filter(
                CandidateModel.is_training_example == True,  # noqa: E712
                CandidateModel.actual_score.isnot(None),
                CandidateModel.category_id == category_id,
            )
            .all()
        )

    def count_unrendered_by_video(self, video_id: int) -> int:
        """Count candidates for a video that have no completed clip yet."""
        from app.models.clip_model import ClipModel
        rendered_candidate_ids = (
            self.db.query(ClipModel.candidate_id)
            .filter(
                ClipModel.video_id == video_id,
                ClipModel.status == "completed",
            )
            .subquery()
        )
        return (
            self.db.query(CandidateModel)
            .filter(
                CandidateModel.video_id == video_id,
                CandidateModel.id.notin_(rendered_candidate_ids),
            )
            .count()
        )
