"""Training endpoints: bulk CSV import, model training, dashboard, dan riwayat."""

import logging
import shutil

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config.settings import settings
from app.core.di.dependencies import (
    get_category_service,
    get_model_trainer,
    get_training_import_service,
    get_training_run_repo,
    get_training_stats_service,
)
from app.core.exceptions.base import NotFoundException, ValidationException
from app.core.htmx import render
from app.ml.trainer import ModelTrainer
from app.repositories.training_run_repository import TrainingRunRepository
from app.services.category_service import CategoryService
from app.services.training_import_service import TrainingImportService
from app.services.training_stats_service import TrainingStatsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/training", tags=["training"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def training_import_page(
    request: Request,
    category_service: CategoryService = Depends(get_category_service),
) -> HTMLResponse:
    """Render halaman bulk CSV import untuk training clip."""
    categories = category_service.list_categories()
    return render(
        request,
        templates,
        partial_name="training_import.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "categories": categories,
        },
    )


@router.get("/template.csv")
def download_template_csv():
    """Download template CSV kosong dengan header dan 3 baris contoh."""
    from fastapi.responses import Response
    content = (
        "source,actual_score\n"
        "C:\\Users\\Anda\\Videos\\contoh_clip1.mp4,8.5\n"
        "C:\\Users\\Anda\\Videos\\contoh_clip2.mp4,6.0\n"
        "https://youtu.be/MASUKKAN_ID_VIDEO_DISINI,9.0\n"
        "https://www.tiktok.com/@user/video/MASUKKAN_ID_DISINI,7.5\n"
    )
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=training_template.csv"},
    )


@router.post("/bulk-import", response_class=HTMLResponse)
async def bulk_import_training(
    request: Request,
    file: UploadFile = File(...),
    category_id: int = Form(...),
    service: TrainingImportService = Depends(get_training_import_service),
) -> HTMLResponse:
    """CSV format: source,actual_score
    source boleh path file lokal ATAU URL video.
    Contoh baris:
        /path/to/clip1.mp4,8.5
        https://youtu.be/xxxxx,9.0
    Semua baris ditandai kategori yang sama (category_id dari form).
    """
    rows = await service.parse_csv(file)
    import_id, job_ids = service.enqueue_bulk_ingest(rows, category_id=category_id)
    progress = service.get_import_progress(import_id)  # context lengkap dari awal
    return templates.TemplateResponse(
        request=request,
        name="_import_progress.html",
        context={
            "request": request,
            **progress,  # sudah termasuk import_id, status, total, completed, failed, percent
        }
    )


@router.get("/bulk-import/{import_id}", response_class=HTMLResponse)
def get_import_progress(
    request: Request,
    import_id: str,
    service: TrainingImportService = Depends(get_training_import_service),
) -> HTMLResponse:
    """Baca progress bulk import (untuk polling dari UI)."""
    progress = service.get_import_progress(import_id)
    return templates.TemplateResponse(
        request=request,
        name="_import_progress.html",
        context={
            "request": request,
            "import_id": import_id,
            **progress
        }
    )


@router.get("/dashboard", response_class=HTMLResponse)
def training_dashboard(
    request: Request,
    category_id: int | None = None,
    stats_service: TrainingStatsService = Depends(get_training_stats_service),
    category_service: CategoryService = Depends(get_category_service),
) -> HTMLResponse:
    """Halaman training dashboard — per kategori, dipilih lewat dropdown.

    Kategori terakhir yang dipilih disimpan di cookie (training_category_id),
    jadi pindah page / kembali dari bulk import tidak me-reset ke kategori
    pertama. Query param ?category_id tetap menang kalau diberikan.
    """
    categories = category_service.list_categories()

    if category_id is None:
        # Fallback ke cookie (kategori terakhir) kalau kategori tsb masih ada
        saved = request.cookies.get("training_category_id")
        if saved and saved.isdigit():
            candidate = int(saved)
            if any(c.id == candidate for c in categories):
                category_id = candidate

    if category_id is None and categories:
        category_id = categories[0].id  # default ke kategori pertama

    stats = stats_service.get_stats(category_id) if category_id else {
        "total": 0, "counts_by_source": {}, "training_runs": [], "active_run": None,
    }

    tpl = render(
        request, templates,
        partial_name="training_dashboard_content.html",
        context={
            "request": request,
            "app_name": settings.APP_NAME,
            "categories": categories,
            "selected_category_id": category_id,
            **stats,
        },
    )
    if category_id is not None:
        tpl.set_cookie("training_category_id", str(category_id))
    return tpl


@router.post("/train")
def train_model(
    request: Request,
    category_id: int,
    service: ModelTrainer = Depends(get_model_trainer),
):
    """Latih model untuk SATU kategori."""
    try:
        run = service.train(category_id)
    except ValueError as e:
        raise ValidationException(str(e))

    # Return HTML snippet for htmx, JSON for API
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="_train_result.html",
            context={
                "request": request,
                "run": run,
            },
        )
    return {
        "id": run.id,
        "sample_count": run.sample_count,
        "val_mae": run.val_mae,
        "val_r2": run.val_r2,
        "is_active": run.is_active,
    }


@router.get("/runs")
def list_training_runs(
    category_id: int,
    repo: TrainingRunRepository = Depends(get_training_run_repo),
) -> list:
    """Semua riwayat training untuk satu kategori, terbaru dulu."""
    runs = repo.get_all(category_id)
    return [
        {
            "id": r.id,
            "category_id": r.category_id,
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
    request: Request,
    run_id: int,
    repo: TrainingRunRepository = Depends(get_training_run_repo),
    stats_service: TrainingStatsService = Depends(get_training_stats_service),
    category_service: CategoryService = Depends(get_category_service),
):
    """Rollback/aktifkan model dari run tertentu (bukan cuma yang terbaru)."""
    run = repo.get(run_id)
    if run is None:
        raise NotFoundException(f"Training run {run_id} tidak ditemukan")

    from pathlib import Path
    model_path = Path(run.model_file_path)
    if not model_path.exists():
        raise NotFoundException(
            f"File model untuk run {run_id} tidak ditemukan di disk"
        )

    # GANTI dari MODEL_PATH (sudah dihapus sejak file 07) jadi path per-kategori:
    active_path = Path(f"data/models/category_{run.category_id}/score_model.pkl")
    active_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(model_path, active_path)

    activated = repo.set_active(run_id)
    logger.info("Model run %d (kategori %d) diaktifkan manual", run_id, run.category_id)

    # Return full dashboard partial for htmx, JSON for API
    if request.headers.get("HX-Request"):
        categories = category_service.list_categories()
        stats = stats_service.get_stats(run.category_id)
        return render(
            request,
            templates,
            partial_name="training_dashboard_content.html",
            context={
                "request": request,
                "app_name": settings.APP_NAME,
                "categories": categories,
                "selected_category_id": run.category_id,
                **stats,
            },
        )
    return {
        "id": activated.id,
        "is_active": activated.is_active,
        "val_mae": activated.val_mae,
        "val_r2": activated.val_r2,
    }
