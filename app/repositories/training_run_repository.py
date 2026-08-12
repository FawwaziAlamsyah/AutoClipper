"""Repository for TrainingRunModel."""

from app.models.training_run_model import TrainingRunModel
from app.repositories.base_repository import PostgresRepository


class TrainingRunRepository(PostgresRepository[TrainingRunModel]):
    """PostgreSQL repository for training_runs."""

    model_class = TrainingRunModel

    def get_all(self) -> list[TrainingRunModel]:
        """Semua run, terbaru dulu."""
        return list(
            self.db.query(TrainingRunModel)
            .order_by(TrainingRunModel.trained_at.desc())
            .all()
        )

    def get_active(self) -> TrainingRunModel | None:
        """Run yang sedang aktif dipakai predictor.py."""
        return (
            self.db.query(TrainingRunModel)
            .filter(TrainingRunModel.is_active == True)  # noqa: E712
            .first()
        )

    def set_active(self, run_id: int) -> TrainingRunModel:
        """Set satu run jadi aktif, matikan flag aktif di run lain (cuma boleh 1 aktif)."""
        self.db.query(TrainingRunModel).update({"is_active": False})
        run = self.db.query(TrainingRunModel).filter(TrainingRunModel.id == run_id).first()
        if run is None:
            raise ValueError(f"Training run {run_id} not found")
        run.is_active = True
        self.db.commit()
        self.db.refresh(run)
        return run
