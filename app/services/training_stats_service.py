"""Service untuk statistik data training + riwayat training runs dari database."""

import logging

from sqlalchemy.orm import Session

from app.repositories.candidate_repository import CandidateRepository
from app.repositories.training_run_repository import TrainingRunRepository

logger = logging.getLogger(__name__)

LABEL_SOURCES = ("real_performance", "user_liked", "user_disliked")


class TrainingStatsService:
    """Ringkasan data training dan riwayat training runs."""

    def __init__(self, db: Session) -> None:
        """Init dengan DB session."""
        self.db = db
        self.candidate_repo = CandidateRepository(db)
        self.run_repo = TrainingRunRepository(db)

    def get_stats(self) -> dict:
        """Return jumlah training example per label_source + daftar semua training runs."""
        candidates = self.candidate_repo.get_training_examples()

        counts_by_source = {src: 0 for src in LABEL_SOURCES}
        for cand in candidates:
            src = cand.label_source or "unknown"
            if src in counts_by_source:
                counts_by_source[src] += 1

        total = len(candidates)

        # Semua riwayat training run dari database (terbaru dulu)
        training_runs = self.run_repo.get_all()

        # Model aktif saat ini (untuk tampilan "Model Terakhir")
        active_run = self.run_repo.get_active()

        # Urutkan feature_importance descending untuk tampilan UI (jika ada)
        for run in training_runs:
            if run.feature_importance:
                run.feature_importance = dict(
                    sorted(
                        run.feature_importance.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                )

        return {
            "total": total,
            "counts_by_source": counts_by_source,
            "training_runs": training_runs,
            "active_run": active_run,
        }
