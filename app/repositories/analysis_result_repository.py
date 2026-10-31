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
        """Get analysis results for a specific job window.

        Mendukung toleransi float precision (0.15 detik) dan menyertakan analisis
        global (start_time is None) agar selaras 1:1 dengan cand_analysis pada ScoreEngine.
        """
        from sqlalchemy import and_, func, or_
        return list(
            self.db.query(AnalysisResultModel)
            .filter(
                AnalysisResultModel.job_id == job_id,
                or_(
                    and_(
                        func.abs(AnalysisResultModel.start_time - start_time) < 0.15,
                        func.abs(AnalysisResultModel.end_time - end_time) < 0.15,
                    ),
                    AnalysisResultModel.start_time.is_(None),
                ),
            )
            .all()
        )
