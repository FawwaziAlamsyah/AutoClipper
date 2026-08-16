# Category Training 14 — `training_router.py` Per Kategori

Bagian 14 dari 16. **Prasyarat: file 01-13 sudah selesai.**

Catatan: seri ini awalnya direncanakan 14 file, tapi bagian dashboard/UI
ternyata terlalu besar untuk 1 file — dipecah jadi file 14, 15, 16. Nomor
akhir seri jadi 16, bukan 14.

## Task — `GET /training/dashboard` Terima `category_id`

Di `app/routers/training_router.py`:

```python
@router.get("/dashboard", response_class=HTMLResponse)
def training_dashboard(
    request: Request,
    category_id: int | None = None,
    stats_service: TrainingStatsService = Depends(get_training_stats_service),
    category_service: CategoryService = Depends(get_category_service),
) -> HTMLResponse:
    """Halaman training dashboard — per kategori, dipilih lewat dropdown."""
    categories = category_service.list_categories()

    if category_id is None and categories:
        category_id = categories[0].id  # default ke kategori pertama

    stats = stats_service.get_stats(category_id) if category_id else {
        "total": 0, "counts_by_source": {}, "training_runs": [], "active_run": None,
    }

    return render(
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
```

## Task — `POST /training/train` Wajib `category_id`

```python
@router.post("/train")
def train_model(
    request: Request,
    category_id: int,
    service: ModelTrainer = Depends(get_model_trainer),
) -> HTMLResponse | dict:
    """Latih model untuk SATU kategori."""
    try:
        run = service.train(category_id)
    except ValueError as e:
        raise ValidationException(str(e))
    # ... sisa logic (return HTML utk htmx / JSON utk API) TIDAK BERUBAH
```

## Task — `POST /training/runs/{run_id}/activate` — Perbaiki Referensi Path Lama

```python
@router.post("/runs/{run_id}/activate")
def activate_training_run(
    request: Request,
    run_id: int,
    repo: TrainingRunRepository = Depends(get_training_run_repo),
):
    run = repo.get(run_id)
    if run is None:
        raise NotFoundException(f"Training run {run_id} tidak ditemukan")

    from pathlib import Path
    model_path = Path(run.model_file_path)
    if not model_path.exists():
        raise NotFoundException(f"File model untuk run {run_id} tidak ditemukan di disk")

    # GANTI dari MODEL_PATH (sudah dihapus sejak file 07) jadi path per-kategori:
    active_path = Path(f"data/models/category_{run.category_id}/score_model.pkl")
    active_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(model_path, active_path)

    activated = repo.set_active(run_id)
    logger.info("Model run %d (kategori %d) diaktifkan manual", run_id, run.category_id)
    # ... sisa return TIDAK BERUBAH
```

**Penting**: cari baris import di paling atas file
`from app.ml.trainer import MODEL_PATH, ModelTrainer` — ganti jadi
`from app.ml.trainer import ModelTrainer` saja (`MODEL_PATH` sudah dihapus
sejak file 07, import ini akan error kalau tidak diperbaiki).

## Task — `GET /training/runs` Tambah Filter `category_id`

```python
@router.get("/runs")
def list_training_runs(
    category_id: int,
    repo: TrainingRunRepository = Depends(get_training_run_repo),
) -> list:
    runs = repo.get_all(category_id)
    # ... sisa logic TIDAK BERUBAH
```

## Definisi Selesai

- `python -m py_compile app/routers/training_router.py` lulus — khususnya
  pastikan TIDAK ADA lagi `from app.ml.trainer import MODEL_PATH`.
- `GET /training/dashboard` (tanpa query param) → tidak error walau belum
  ada kategori sama sekali (`categories` kosong, `category_id` jadi None,
  stats default kosong ditampilkan).
- `POST /training/train?category_id=1` pada kategori yang datanya masih
  kurang dari 20 → error jelas (dari `ModelTrainer.train()`), bukan crash.
- `pytest` tetap lulus.
- **Jangan lanjut ke file 15** sebelum poin di atas terverifikasi.
