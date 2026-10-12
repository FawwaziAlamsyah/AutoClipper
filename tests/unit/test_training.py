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
