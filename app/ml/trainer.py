"""Latih model scoring dari data training yang terkumpul."""

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
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


class ModelTrainer:
    """Latih dan simpan model scoring dari training_example candidates."""

    def __init__(self, db: Session) -> None:
        """Init dengan DB session dan repositories."""
        self.db = db
        self.candidate_repo = CandidateRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.run_repo = TrainingRunRepository(db)

    def train(self, category_id: int) -> TrainingRunModel:
        """Latih model untuk satu kategori, simpan versioned + aktif."""
        candidates = self.candidate_repo.get_training_examples(category_id=category_id)
        if len(candidates) < 20:
            raise ValueError(
                f"Data training kategori ini terlalu sedikit ({len(candidates)} row). "
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

        # Variance Guard: pastikan label target tidak seragam (Var(y) > 0)
        distinct_y = set(y)
        if len(distinct_y) < 2:
            val = y[0] if y else 0.0
            raise ValueError(
                f"Data training kategori ini tidak memiliki variasi nilai (semua bernilai {val:.1f}). "
                "Minimal dibutuhkan kombinasi klip disukai (Like / skor tinggi) dan klip ditolak "
                "(Dislike / skor rendah) atau impor data performa riil agar model dapat belajar membedakan kualitas klip."
            )

        import numpy as np
        from sklearn.model_selection import KFold

        X_arr = np.array(X)
        y_arr = np.array(y)
        w_arr = np.array(sample_weight)

        n_samples = len(X_arr)
        # 5-fold CV untuk n >= 25; split adaptif untuk 20 <= n < 25
        n_splits = 5 if n_samples >= 25 else min(5, max(2, n_samples // 4))

        kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
        val_predictions = np.zeros(n_samples)

        for train_idx, val_idx in kf.split(X_arr):
            fold_model = GradientBoostingRegressor(
                n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42
            )
            fold_model.fit(X_arr[train_idx], y_arr[train_idx], sample_weight=w_arr[train_idx])
            val_predictions[val_idx] = fold_model.predict(X_arr[val_idx])

        mae = float(mean_absolute_error(y_arr, val_predictions))
        r2 = float(r2_score(y_arr, val_predictions))

        # Latih model produksi final menggunakan seluruh dataset
        model = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42
        )
        model.fit(X_arr, y_arr, sample_weight=w_arr)

        category_dir = Path(f"data/models/category_{category_id}")
        versioned_dir = category_dir / "versions"
        versioned_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        versioned_path = versioned_dir / f"score_model_{timestamp}.pkl"
        joblib.dump(model, versioned_path)

        active_path = category_dir / "score_model.pkl"
        shutil.copy(versioned_path, active_path)

        feature_importance = dict(zip(FEATURE_ORDER, model.feature_importances_.tolist()))

        run = self.run_repo.add(TrainingRunModel(
            category_id=category_id,
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

        self.db.query(TrainingRunModel).filter(
            TrainingRunModel.category_id == category_id,
            TrainingRunModel.id != run.id,
        ).update({"is_active": False})
        self.db.commit()

        logger.info(
            "Model kategori %d trained (run %d): %d samples, val_mae=%.3f, val_r2=%.3f",
            category_id, run.id, len(candidates), mae, r2,
        )
        return run
