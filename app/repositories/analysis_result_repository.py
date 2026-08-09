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

    def get_by_type(self, job_id: int, analyzer_type: str) -> list[AnalysisResultModel]:
        """Get analysis results for a specific analyzer type within a job."""
        return list(
            self.db.query(AnalysisResultModel)
            .filter(
                AnalysisResultModel.job_id == job_id,
                AnalysisResultModel.analyzer_type == analyzer_type,
            )
            .order_by(AnalysisResultModel.start_time)
            .all()
        )
