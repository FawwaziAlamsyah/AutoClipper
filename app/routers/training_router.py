"""Training endpoints: bulk CSV import, model training, dashboard, dan riwayat."""

import logging
import shutil

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.di.dependencies import (
    get_model_trainer,
    get_training_import_service,
    get_training_run_repo,
    get_training_stats_service,
)
from app.core.exceptions.base import NotFoundException, ValidationException
from app.ml.trainer import MODEL_PATH, ModelTrainer
from app.repositories.training_run_repository import TrainingRunRepository
from app.services.training_import_service import TrainingImportService
from app.services.training_stats_service import TrainingStatsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/training", tags=["training"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def training_import_page(request: Request) -> HTMLResponse:
    """Render halaman bulk CSV import untuk training clip."""
    return templates.TemplateResponse(
        request=request,
        name="training_import.html",
        context={"app_name": settings.APP_NAME},
    )


@router.post("/bulk-import")
async def bulk_import_training(
    file: UploadFile = File(...),
    service: TrainingImportService = Depends(get_training_import_service),
) -> dict:
    """CSV format: source,actual_score
    source boleh path file lokal ATAU URL video.
    Contoh baris:
        /path/to/clip1.mp4,8.5
        https://youtu.be/xxxxx,9.0
    """
    rows = await service.parse_csv(file)
    import_id, job_ids = service.enqueue_bulk_ingest(rows)
    return {"import_id": import_id, "queued": len(rows), "job_ids": job_ids}


@router.get("/bulk-import/{import_id}")
def get_import_progress(
    import_id: str,
    service: TrainingImportService = Depends(get_training_import_service),
) -> dict:
    """Baca progress bulk import (untuk polling dari UI)."""
    return service.get_import_progress(import_id)


@router.get("/dashboard", response_class=HTMLResponse)
def training_dashboard(
    request: Request,
    service: TrainingStatsService = Depends(get_training_stats_service),
) -> HTMLResponse:
    """Halaman ringkasan data training + riwayat training runs."""
    stats = service.get_stats()
    return templates.TemplateResponse(
        request=request,
        name="training_dashboard.html",
        context={
            "app_name": settings.APP_NAME,
            **stats,
        },
    )


@router.post("/train")
def train_model(
    service: ModelTrainer = Depends(get_model_trainer),
) -> dict:
    """Latih model dari semua training example yang terkumpul, return run metrics."""
    try:
        run = service.train()
    except ValueError as e:
        raise ValidationException(str(e))
    return {
        "id": run.id,
        "sample_count": run.sample_count,
        "val_mae": run.val_mae,
        "val_r2": run.val_r2,
        "is_active": run.is_active,
    }


@router.get("/runs")
def list_training_runs(
    repo: TrainingRunRepository = Depends(get_training_run_repo),
) -> list:
    """Semua riwayat training, terbaru dulu."""
    runs = repo.get_all()
    return [
        {
            "id": r.id,
            "trained_at": r.trained_at.isoformat() if r.trained_at else None,
            "sample_count": r.sample_count,
            "real_performance_count": r.real_performance_count,
            "user_liked_count": r.user_liked_count,
            "auto_rejected_count": r.auto_rejected_count,
            "val_mae": r.val_mae,
            "val_r2": r.val_r2,
            "model_file_path": r.model_file_path,
            "is_active": r.is_active,
        }
        for r in runs
    ]


@router.post("/runs/{run_id}/activate")
def activate_training_run(
    run_id: int,
    repo: TrainingRunRepository = Depends(get_training_run_repo),
) -> dict:
    """Rollback/aktifkan model dari run tertentu (bukan cuma yang terbaru)."""
    run = repo.get(run_id)
    if run is None:
        raise NotFoundException(f"Training run {run_id} tidak ditemukan")

    from pathlib import Path
    model_path = Path(run.model_file_path)
    if not model_path.exists():
        raise NotFoundException(
            f"File model untuk run {run_id} tidak ditemukan di disk: {run.model_file_path}"
        )

    shutil.copy(model_path, MODEL_PATH)
    activated = repo.set_active(run_id)
    logger.info("Model run %d diaktifkan manual (rollback/switch)", run_id)
    return {
        "id": activated.id,
        "is_active": activated.is_active,
        "val_mae": activated.val_mae,
        "val_r2": activated.val_r2,
    }
