"""Repository for AnalysisResult model."""

from app.models.analysis_result_model import AnalysisResultModel
from app.repositories.base_repository import PostgresRepository


class AnalysisResultRepository(PostgresRepository[AnalysisResultModel]):
    """PostgreSQL repository for analysis results."""

    model_class = AnalysisResultModel

    def get_by_job(self, job_id: int) -> list[AnalysisResultModel]:
        """Get all analysis results for a job."""
        return list(
            self.db.query(AnalysisResultModel)
            .filter(AnalysisResultModel.job_id == job_id)
            .all()
        )

    def get_by_job_and_window(
        self,
        job_id: int,
        start_time: float,
        end_time: float,
    ) -> list[AnalysisResultModel]:
        """Get analysis results for a specific job window (exact start/end match).

        Dipakai oleh trainer.py untuk membangun feature vector per candidate —
        start/end dari analysis_results selalu sama persis dengan window
        candidate karena analysis_service membuat keduanya dari sumber yang sama.
        """
        return list(
            self.db.query(AnalysisResultModel)
            .filter(
                AnalysisResultModel.job_id == job_id,
                AnalysisResultModel.start_time == start_time,
                AnalysisResultModel.end_time == end_time,
            )
            .all()
        )
