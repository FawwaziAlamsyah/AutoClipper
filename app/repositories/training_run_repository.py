"""Repository for TrainingRunModel."""

from app.models.training_run_model import TrainingRunModel
from app.repositories.base_repository import PostgresRepository


class TrainingRunRepository(PostgresRepository[TrainingRunModel]):
    """PostgreSQL repository for training_runs."""

    model_class = TrainingRunModel

    def get_all(self, category_id: int) -> list[TrainingRunModel]:
        """Semua run UNTUK SATU KATEGORI, terbaru dulu."""
        return list(
            self.db.query(TrainingRunModel)
            .filter(TrainingRunModel.category_id == category_id)
            .order_by(TrainingRunModel.trained_at.desc())
            .all()
        )

    def get_active(self, category_id: int) -> TrainingRunModel | None:
        """Run yang sedang aktif UNTUK SATU KATEGORI."""
        return (
            self.db.query(TrainingRunModel)
            .filter(TrainingRunModel.category_id == category_id, TrainingRunModel.is_active == True)  # noqa: E712
            .first()
        )

    def set_active(self, run_id: int) -> TrainingRunModel:
        """Set satu run jadi aktif — cuma matikan flag run LAIN DI KATEGORI YANG SAMA."""
        run = self.db.query(TrainingRunModel).filter(TrainingRunModel.id == run_id).first()
        if run is None:
            raise ValueError(f"Training run {run_id} not found")
        self.db.query(TrainingRunModel).filter(
            TrainingRunModel.category_id == run.category_id
        ).update({"is_active": False})
        run.is_active = True
        self.db.commit()
        self.db.refresh(run)
        return run
