"""Unit tests for training run repository and delete endpoints."""

from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from app.core.exceptions.base import NotFoundException
from app.models.category_model import CategoryModel
from app.models.training_run_model import TrainingRunModel
from app.repositories.category_repository import CategoryRepository
from app.repositories.training_run_repository import TrainingRunRepository
from app.routers.training_router import clear_training_runs, delete_training_run


def test_training_run_repository_crud(db_session: Session) -> None:
    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Training Test Cat"))

    repo = TrainingRunRepository(db_session)

    run1 = repo.add(TrainingRunModel(
        category_id=cat.id,
        sample_count=25,
        val_mae=0.45,
        val_r2=0.82,
        model_file_path="data/models/cat/test.pkl",
        is_active=False,
        trained_at=datetime.now(timezone.utc),
    ))
    assert run1.id is not None
    assert run1.category_id == cat.id

    runs = repo.get_all(cat.id)
    assert len(runs) >= 1
    assert any(r.id == run1.id for r in runs)

    # Set active
    activated = repo.set_active(run1.id)
    assert activated.is_active is True
    assert repo.get_active(cat.id).id == run1.id

    # Delete
    assert repo.delete(run1.id) is True
    assert repo.get(run1.id) is None


def test_delete_training_run_endpoint(db_session: Session, tmp_path: Path) -> None:
    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Delete Run Cat"))

    repo = TrainingRunRepository(db_session)

    # Create dummy model file
    dummy_model = tmp_path / "model_dummy.pkl"
    dummy_model.write_text("model weights")

    run = repo.add(TrainingRunModel(
        category_id=cat.id,
        sample_count=30,
        val_mae=0.35,
        val_r2=0.88,
        is_active=True,
        model_file_path=str(dummy_model),
        trained_at=datetime.now(timezone.utc),
    ))

    res = delete_training_run(run.id, repo=repo)
    assert res["ok"] is True
    assert res["deleted_id"] == run.id
    assert repo.get(run.id) is None
    assert not dummy_model.exists()

    # Deleting non-existent should raise 404
    with pytest.raises(NotFoundException):
        delete_training_run(999999, repo=repo)


def test_clear_training_runs_endpoint(db_session: Session, tmp_path: Path) -> None:
    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Clear Runs Cat"))

    repo = TrainingRunRepository(db_session)

    dummy1 = tmp_path / "run1.pkl"
    dummy1.write_text("w1")
    dummy2 = tmp_path / "run2.pkl"
    dummy2.write_text("w2")

    repo.add(TrainingRunModel(
        category_id=cat.id,
        sample_count=20,
        val_mae=0.40,
        val_r2=0.75,
        model_file_path=str(dummy1),
        is_active=False,
    ))
    repo.add(TrainingRunModel(
        category_id=cat.id,
        sample_count=25,
        val_mae=0.30,
        val_r2=0.85,
        model_file_path=str(dummy2),
        is_active=True,
    ))

    assert len(repo.get_all(cat.id)) == 2

    res = clear_training_runs(category_id=cat.id, repo=repo)
    assert res["ok"] is True
    assert res["count"] == 2
    assert len(repo.get_all(cat.id)) == 0
    assert not dummy1.exists()
    assert not dummy2.exists()


def test_training_stats_service_includes_disliked(db_session: Session) -> None:
    """TrainingStatsService should count user_disliked candidates."""
    from app.services.training_stats_service import TrainingStatsService
    from app.models.candidate_model import CandidateModel
    from app.models.video_model import VideoModel
    from app.models.job_model import JobModel

    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Stats Test Cat"))

    video = VideoModel(
        original_filename="stats_test.mp4",
        file_path="stats_test.mp4",
        source_type="upload",
        status="ready",
    )
    db_session.add(video)
    db_session.commit()

    job = JobModel(video_id=video.id, status="completed", category_id=cat.id, pipeline_name="full_pipeline")
    db_session.add(job)
    db_session.commit()

    cand1 = CandidateModel(
        video_id=video.id,
        job_id=job.id,
        start_time=0.0,
        end_time=30.0,
        category_id=cat.id,
        is_training_example=True,
        final_score=8.0,
        actual_score=8.0,
        label_source="user_liked",
    )
    cand2 = CandidateModel(
        video_id=video.id,
        job_id=job.id,
        start_time=30.0,
        end_time=60.0,
        category_id=cat.id,
        is_training_example=True,
        final_score=2.0,
        actual_score=2.0,
        label_source="user_disliked",
    )
    db_session.add_all([cand1, cand2])
    db_session.commit()

    stats_svc = TrainingStatsService(db_session)
    stats = stats_svc.get_stats(cat.id)

    assert stats["total"] == 2
    assert stats["counts_by_source"]["user_liked"] == 1
    assert stats["counts_by_source"]["user_disliked"] == 1


def test_model_trainer_variance_guard(db_session: Session) -> None:
    """ModelTrainer should raise ValueError if all target actual_scores are identical."""
    from app.ml.trainer import ModelTrainer
    from app.models.candidate_model import CandidateModel
    from app.models.video_model import VideoModel
    from app.models.job_model import JobModel

    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Variance Guard Cat"))

    video = VideoModel(original_filename="v.mp4", file_path="v.mp4", source_type="upload", status="ready")
    db_session.add(video)
    db_session.commit()

    job = JobModel(video_id=video.id, status="completed", category_id=cat.id, pipeline_name="full_pipeline")
    db_session.add(job)
    db_session.commit()

    # 20 samples all with score 8.0
    cands = [
        CandidateModel(
            video_id=video.id,
            job_id=job.id,
            start_time=float(i * 10),
            end_time=float(i * 10 + 30),
            category_id=cat.id,
            is_training_example=True,
            final_score=8.0,
            actual_score=8.0,
            label_source="user_liked",
        )
        for i in range(20)
    ]
    db_session.add_all(cands)
    db_session.commit()

    trainer = ModelTrainer(db_session)
    with pytest.raises(ValueError, match="tidak memiliki variasi nilai"):
        trainer.train(cat.id)


def test_model_trainer_kfold_success(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    """ModelTrainer should train with K-Fold CV and calculate feature importances when variance exists."""
    from app.ml.trainer import ModelTrainer
    from app.models.candidate_model import CandidateModel
    from app.models.video_model import VideoModel
    from app.models.job_model import JobModel
    from app.models.analysis_result_model import AnalysisResultModel

    # Redirect data/models to tmp_path
    monkeypatch.chdir(tmp_path)

    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="KFold Success Cat"))

    video = VideoModel(original_filename="v2.mp4", file_path="v2.mp4", source_type="upload", status="ready")
    db_session.add(video)
    db_session.commit()

    job = JobModel(video_id=video.id, status="completed", category_id=cat.id, pipeline_name="full_pipeline")
    db_session.add(job)
    db_session.commit()

    cands = []
    analyses = []
    # 10 positive (8.0), 10 negative (2.0)
    for i in range(20):
        score = 8.0 if i < 10 else 2.0
        src = "user_liked" if i < 10 else "user_disliked"
        cands.append(
            CandidateModel(
                video_id=video.id,
                job_id=job.id,
                start_time=float(i * 60),
                end_time=float(i * 60 + 60),
                category_id=cat.id,
                is_training_example=True,
                final_score=score,
                actual_score=score,
                label_source=src,
            )
        )
        # Add analysis results with distinct hook scores
        analyses.append(
            AnalysisResultModel(
                video_id=video.id,
                job_id=job.id,
                analyzer_type="hook",
                score=8.5 if i < 10 else 2.5,
                start_time=float(i * 60),
                end_time=float(i * 60 + 60),
            )
        )

    db_session.add_all(cands)
    db_session.add_all(analyses)
    db_session.commit()

    trainer = ModelTrainer(db_session)
    run = trainer.train(cat.id)

    assert run.id is not None
    assert run.sample_count == 20
    assert run.user_liked_count == 10
    assert run.auto_rejected_count == 10
    assert run.val_mae > 0.0
    assert run.is_active is True
    assert "hook" in run.feature_importance


def test_delete_active_training_run_promotes_next(db_session: Session, tmp_path: Path) -> None:
    """Deleting active run should promote the remaining latest run to active."""
    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Promote Cat"))

    repo = TrainingRunRepository(db_session)

    m1 = tmp_path / "m1.pkl"
    m1.write_text("m1")
    m2 = tmp_path / "m2.pkl"
    m2.write_text("m2")

    run_older = repo.add(TrainingRunModel(
        category_id=cat.id,
        sample_count=20,
        val_mae=0.40,
        val_r2=0.75,
        model_file_path=str(m1),
        is_active=False,
    ))
    run_newer = repo.add(TrainingRunModel(
        category_id=cat.id,
        sample_count=25,
        val_mae=0.30,
        val_r2=0.85,
        model_file_path=str(m2),
        is_active=True,
    ))

    res = delete_training_run(run_newer.id, repo=repo)
    assert res["ok"] is True

    active = repo.get_active(cat.id)
    assert active is not None
    assert active.id == run_older.id


def test_model_trainer_insufficient_samples(db_session: Session) -> None:
    """ModelTrainer should raise ValueError if sample count is less than 20."""
    from app.ml.trainer import ModelTrainer

    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Low Samples Cat"))

    trainer = ModelTrainer(db_session)
    with pytest.raises(ValueError, match="terlalu sedikit"):
        trainer.train(cat.id)


def test_predictor_rejects_degenerate_model(tmp_path: Path, monkeypatch) -> None:
    """Predictor should return None and fallback to weighted-sum if model feature_importances are all 0."""
    import joblib
    from sklearn.ensemble import GradientBoostingRegressor
    from app.ml.predictor import predict_score, _model_cache

    monkeypatch.chdir(tmp_path)
    model_dir = tmp_path / "data" / "models" / "category_999"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "score_model.pkl"

    # Create dummy degenerate model
    model = GradientBoostingRegressor(n_estimators=10)
    # Fit on constant target so feature_importances are all 0
    import numpy as np
    model.fit(np.zeros((10, 11)), np.ones(10) * 8.0)
    joblib.dump(model, model_path)

    _model_cache.clear()
    score = predict_score([], category_id=999)
    assert score is None


def test_training_import_progress_error_tracking() -> None:
    """TrainingImportService should track error details in get_import_progress."""
    from app.services.training_import_service import TrainingImportService, _IMPORTS

    service = TrainingImportService(None)
    _IMPORTS["test_import_123"] = {
        "total": 5,
        "queued": 0,
        "completed": 4,
        "failed": 1,
        "jobs": [1, 2, 3, 4],
        "errors": [{"source": "http://example.com/bad.mp4", "error": "429 Too Many Requests"}],
    }

    prog = service.get_import_progress("test_import_123")
    assert prog["status"] == "finished"
    assert prog["failed"] == 1
    assert len(prog["errors"]) == 1
    assert prog["errors"][0]["source"] == "http://example.com/bad.mp4"
    assert "429" in prog["errors"][0]["error"]


def test_category_deletion_cascades_training_runs(db_session: Session) -> None:
    """Deleting category should safely delete associated training runs without FK error."""
    from app.services.category_service import CategoryService

    cat_repo = CategoryRepository(db_session)
    cat = cat_repo.add(CategoryModel(name="Cascade Delete Cat"))

    repo = TrainingRunRepository(db_session)
    repo.add(TrainingRunModel(
        category_id=cat.id,
        sample_count=20,
        val_mae=0.40,
        val_r2=0.75,
        model_file_path="data/models/cat/test.pkl",
        is_active=False,
    ))

    cat_service = CategoryService(db_session)
    cat_service.delete_category(cat.id)

    # Category and runs should both be deleted
    assert cat_repo.get(cat.id) is None
    assert len(repo.get_all(cat.id)) == 0
