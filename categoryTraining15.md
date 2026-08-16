# Category Training 15 — CSV Bulk Import Wajib Pilih Kategori

Bagian 15 dari 16. **Prasyarat: file 01-14 sudah selesai.**

## Task — Dropdown Kategori di Halaman Import

Di `app/templates/training_import.html`, tambahkan sebelum input file CSV:

```html
<div class="mb-3">
  <label class="form-label">Kategori</label>
  <select class="form-select" name="category_id" required>
    <option value="">-- Pilih kategori --</option>
    {% for cat in categories %}
    <option value="{{ cat.id }}">{{ cat.name }}</option>
    {% endfor %}
  </select>
</div>
```

## Task — Kirim `categories` ke Template

Cari route yang render `training_import.html` (kemungkinan
`training_import_page()` di `training_router.py`) — tambahkan
`category_service.list_categories()` ke context yang dikirim, sama seperti
pola di `training_dashboard()` (file 14).

## Task — `TrainingImportService` Terima `category_id`

Di `app/services/training_import_service.py`:

```python
def enqueue_bulk_ingest(self, rows: list[dict], category_id: int) -> tuple[str, list]:
    """Proses semua baris CSV, SEMUA ditandai kategori yang sama."""
    # ... logic loop per baris TIDAK BERUBAH, KECUALI:
    # di dalam _run_row, cari baris "candidate.actual_score = actual_score"
    # yang sudah ada, tambahkan TEPAT DI BAWAHNYA:
    candidate.category_id = category_id
```

`parse_csv()` **tidak perlu diubah** — tetap parse `source` + `actual_score`
per baris saja. `category_id` sama untuk SEMUA baris dalam satu file CSV,
jadi cukup dikirim sekali sebagai parameter terpisah ke
`enqueue_bulk_ingest`, bukan kolom baru di CSV.

## Task — Update Endpoint `POST /training/bulk-import`

Di `training_router.py`, terima `category_id` dari form dan teruskan:

```python
@router.post("/bulk-import", response_class=HTMLResponse)
async def bulk_import_training(
    request: Request,
    file: UploadFile = File(...),
    category_id: int = Form(...),
    service: TrainingImportService = Depends(get_training_import_service),
) -> HTMLResponse:
    rows = await service.parse_csv(file)
    import_id, job_ids = service.enqueue_bulk_ingest(rows, category_id=category_id)
    # ... sisa logic TIDAK BERUBAH
```

## Definisi Selesai

- `python -m py_compile app/services/training_import_service.py app/routers/training_router.py`
  lulus.
- Buka halaman Training Import → ada dropdown kategori sebelum input CSV.
- Submit form TANPA pilih kategori → ditolak dengan pesan jelas (validasi
  `required` di HTML + `Form(...)` wajib di endpoint), bukan diproses
  dengan kategori kosong.
- Upload CSV kecil (2-3 baris) dengan kategori dipilih → setelah selesai,
  cek database: candidate hasil import punya `category_id` sesuai yang
  dipilih.
- `pytest` tetap lulus.
- **Jangan lanjut ke file 16** sebelum poin di atas terverifikasi.
