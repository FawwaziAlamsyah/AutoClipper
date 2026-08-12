"""Latih model scoring dari data training yang terkumpul."""

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from sqlalchemy.orm import Session

from app.ml.feature_builder import FEATURE_ORDER, build_feature_vector
from app.models.training_run_model import TrainingRunModel
from app.repositories.analysis_result_repository import AnalysisResultRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.training_run_repository import TrainingRunRepository

logger = logging.getLogger(__name__)

# Bobot kepercayaan per sumber label — data performa nyata paling dipercaya,
# dislike dari user dikasih bobot sama dengan liked karena sama-sama label manual.
LABEL_SOURCE_WEIGHTS = {
    "real_performance": 1.0,
    "user_liked": 0.6,
    "user_disliked": 0.6,
}

# File aktif yang dibaca predictor.py — path tetap sama dari TrainingClip 4.
MODEL_PATH = Path("data/models/score_model.pkl")
VERSIONED_MODEL_DIR = Path("data/models/versions")


class ModelTrainer:
    """Latih dan simpan model scoring dari training_example candidates."""

    def __init__(self, db: Session) -> None:
        """Init dengan DB session dan repositories."""
        self.db = db
        self.candidate_repo = CandidateRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.run_repo = TrainingRunRepository(db)

    def train(self) -> TrainingRunModel:
        """Latih model, simpan versioned + aktif, return TrainingRunModel."""
        candidates = self.candidate_repo.get_training_examples()
        if len(candidates) < 20:
            raise ValueError(
                f"Data training terlalu sedikit ({len(candidates)} row). "
                "Minimal 20 contoh (disarankan 100+) sebelum training."
            )

        X, y, sample_weight, label_sources = [], [], [], []
        for cand in candidates:
            analysis = self.analysis_repo.get_by_job_and_window(
                cand.job_id, cand.start_time, cand.end_time
            )
            X.append(build_feature_vector(analysis))
            y.append(cand.actual_score)
            sample_weight.append(LABEL_SOURCE_WEIGHTS.get(cand.label_source, 0.5))
            label_sources.append(cand.label_source)

        X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
            X, y, sample_weight, test_size=0.2, random_state=42
        )

        model = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42
        )
        model.fit(X_train, y_train, sample_weight=w_train)

        y_pred = model.predict(X_val)
        mae = mean_absolute_error(y_val, y_pred)
        r2 = r2_score(y_val, y_pred)

        # Simpan versioned file — TIDAK ditimpa run berikutnya.
        VERSIONED_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        versioned_path = VERSIONED_MODEL_DIR / f"score_model_{timestamp}.pkl"
        joblib.dump(model, versioned_path)

        # Salin jadi model aktif — ini yang dibaca predictor.py (path tetap sama,
        # tidak perlu ubah apa pun di predictor.py dari TrainingClip 4).
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(versioned_path, MODEL_PATH)

        feature_importance = dict(zip(FEATURE_ORDER, model.feature_importances_.tolist()))

        run = self.run_repo.add(TrainingRunModel(
            sample_count=len(candidates),
            real_performance_count=label_sources.count("real_performance"),
            user_liked_count=label_sources.count("user_liked"),
            auto_rejected_count=label_sources.count("user_disliked"),
            val_mae=round(mae, 3),
            val_r2=round(r2, 3),
            feature_importance=feature_importance,
            model_file_path=str(versioned_path),
            is_active=True,
        ))

        # Matikan flag aktif di run-run sebelumnya.
        self.db.query(TrainingRunModel).filter(TrainingRunModel.id != run.id).update({"is_active": False})
        self.db.commit()

        logger.info(
            "Model trained (run %d): %d samples, val_mae=%.3f, val_r2=%.3f",
            run.id, len(candidates), mae, r2,
        )
        return run
