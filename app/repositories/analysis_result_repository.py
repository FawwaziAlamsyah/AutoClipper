"""Repository for AnalysisResult model."""

from app.models.analysis_result_model import AnalysisResult
from app.repositories.base_repository import PostgresRepository


class AnalysisResultRepository(PostgresRepository[AnalysisResult]):
    """PostgreSQL repository for analysis results."""

    model_class = AnalysisResult

    def get_by_job(self, job_id: int) -> list[AnalysisResult]:
        """Get all analysis results for a job."""
        return list(
            self.db.query(AnalysisResult)
            .filter(AnalysisResult.job_id == job_id)
            .all()
        )

    def get_by_type(self, job_id: int, analyzer_type: str) -> list[AnalysisResult]:
        """Get analysis results for a specific analyzer type within a job."""
        return list(
            self.db.query(AnalysisResult)
            .filter(
                AnalysisResult.job_id == job_id,
                AnalysisResult.analyzer_type == analyzer_type,
            )
            .order_by(AnalysisResult.start_time)
            .all()
        )
