# TrainingClip 2 — Auto-Harvest Kontras, Like Button, Bulk Import

Konteks: lanjutan TrainingClip 1 (kolom `job_type`, `actual_score`,
`is_training_example` sudah ada, mode whole-clip sudah jalan). Tahap ini
menambahkan 3 sumber label baru + cara mengisi 100+ clip Anda secara efisien.

## Task 1 — Kolom `label_source` (provenance tiap label)

### Migrasi baru

Tambahkan kolom `candidates.label_source` — VARCHAR nullable. Nilai yang
dipakai:

- `'real_performance'` — dari clip eksternal Anda (views/likes, TrainingClip 1)
- `'user_liked'` — dari tombol Like di UI (Task 3 di bawah)
- `'auto_rejected'` — dari window yang tidak terpilih top-N (Task 2 di bawah)

Kolom ini penting supaya nanti di TrainingClip 3, tiap sumber label bisa dikasih
**bobot kepercayaan berbeda** saat training — jangan disamaratakan begitu saja,
karena kualitas label-nya beda jauh (data performa nyata jelas lebih bisa
dipercaya daripada tebakan otomatis).

Update endpoint `process-training` dari TrainingClip 1 supaya juga set
`label_source = "real_performance"` saat menyimpan `actual_score`.

## Task 2 — Auto-Harvest Contoh Kontras dari Candidate yang Ditolak

### Kenapa perlu

100+ clip Anda semuanya skor 7-10 (bagus semua) — tidak ada kontras untuk
model belajar bedain bagus vs biasa. Solusinya: pakai window yang **sudah
otomatis tidak lolos top-N** di pipeline normal sebagai sinyal kontras —
gratis, tanpa kerja manual tambahan.

### Perbaikan di `select_top_n()` (`app/services/score_engine.py`)

Saat ini window yang tidak lolos top-N **dihapus** dari database. Ubah supaya
TIDAK dihapus — cukup ditandai, dengan pseudo-label berbasis rank di dalam job
yang sama (BUKAN skor performa nyata — cuma proxy kasar):

```python
def select_top_n(self, job_id: int, n: int) -> list:
    candidates = self.candidate_repo.get_by_job(job_id)
    if not candidates:
        return []

    ranked = sorted(candidates, key=lambda c: c.final_score or 0.0, reverse=True)

    selected: list = []
    for cand in ranked:
        overlaps = any(
            cand.start_time < kept.end_time and cand.end_time > kept.start_time
            for kept in selected
        )
        if not overlaps:
            selected.append(cand)
        if len(selected) >= n:
            break

    rejected = [c for c in candidates if c not in selected]

    # Batasi jumlah yang disimpan sebagai training data — cegah database
    # membengkak dari stream panjang, dan cegah auto-negative membanjiri
    # 100+ label asli Anda secara jumlah saat training nanti.
    sample_size = min(len(rejected), settings.MAX_AUTO_NEGATIVES_PER_JOB)
    harvested = random.sample(rejected, sample_size) if sample_size > 0 else []

    for cand in harvested:
        # Pseudo-label dari percentile rank di job ini sendiri (0-10, kasar).
        # Bukan data performa nyata — makanya label_source ditandai auto_rejected,
        # dan nanti dikasih bobot kepercayaan RENDAH saat training (TrainingClip 3).
        rank_position = ranked.index(cand)
        percentile = 1 - (rank_position / max(len(ranked) - 1, 1))
        cand.actual_score = round(percentile * 10, 2)
        cand.is_training_example = True
        cand.label_source = "auto_rejected"
        cand.status = "rejected"

    # Sisanya (yang tidak ke-harvest & tidak lolos top-N) baru dihapus,
    # sama seperti perilaku sebelumnya.
    drop_ids = [c.id for c in rejected if c not in harvested]
    if drop_ids:
        self.db.query(ClipModel).filter(ClipModel.candidate_id.in_(drop_ids)).delete(synchronize_session=False)
        self.db.query(CandidateModel).filter(CandidateModel.id.in_(drop_ids)).delete(synchronize_session=False)

    self.db.commit()
    logger.info(
        "Job %d: %d selected, %d harvested sebagai auto-negative, %d dihapus",
        job_id, len(selected), len(harvested), len(drop_ids),
    )
    return selected
```

Tambahkan `import random` di atas file, dan `MAX_AUTO_NEGATIVES_PER_JOB: int = 5`
di `app/core/config/settings.py` (boleh disesuaikan — jangan set terlalu besar,
supaya auto-negative tidak mendominasi 100+ label asli Anda secara jumlah).

## Task 3 — Tombol "Like" di Candidate Detail (dengan Konfirmasi)

### Endpoint baru — `app/routers/candidate_router.py`

```python
@router.post("/candidates/{candidate_id}/like")
def like_candidate(
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
):
    """Tandai candidate sebagai contoh bagus untuk training (dari review manual)."""
    candidate = service.mark_as_liked(candidate_id)
    return {"id": candidate.id, "actual_score": candidate.actual_score, "label_source": candidate.label_source}


@router.post("/candidates/{candidate_id}/unlike")
def unlike_candidate(
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
):
    """Batalkan status liked (jaga-jaga salah klik meski sudah ada konfirmasi)."""
    candidate = service.unmark_liked(candidate_id)
    return {"id": candidate.id}
```

### Method baru di `app/services/candidate_service.py`

```python
def mark_as_liked(self, candidate_id: int) -> CandidateModel:
    """Tandai candidate sebagai training example positif dari review manual user."""
    candidate = self.candidate_repo.get(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    candidate.actual_score = settings.LIKED_CLIP_DEFAULT_SCORE
    candidate.is_training_example = True
    candidate.label_source = "user_liked"
    self.db.commit()
    self.db.refresh(candidate)
    logger.info("Candidate %d ditandai liked untuk training", candidate_id)
    return candidate

def unmark_liked(self, candidate_id: int) -> CandidateModel:
    """Batalkan status liked — kembalikan ke kondisi bukan training example."""
    candidate = self.candidate_repo.get(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    if candidate.label_source == "user_liked":
        candidate.actual_score = None
        candidate.is_training_example = False
        candidate.label_source = None
        self.db.commit()
        self.db.refresh(candidate)
    return candidate
```

Tambahkan `LIKED_CLIP_DEFAULT_SCORE: float = 8.0` di `settings.py` — ini skor
default yang dikasih saat user like (bukan performa nyata, makanya lebih rendah
dari clip performa terbaik Anda yang bisa sampai 10, dan bisa Anda ubah nanti
kalau mau lebih konservatif).

### UI di `candidate_detail.html`

Tambahkan tombol di dekat "Generate Clip", plus modal konfirmasi Bootstrap:

```html
<button type="button" class="btn btn-outline-success" id="likeBtn"
        data-bs-toggle="modal" data-bs-target="#likeConfirmModal">
  👍 Like (jadikan contoh training)
</button>

<div class="modal fade" id="likeConfirmModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Konfirmasi Like</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        Tandai clip ini sebagai contoh BAGUS untuk melatih sistem scoring?
        Ini akan mempengaruhi bagaimana sistem menilai clip serupa di masa depan.
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Batal</button>
        <button type="button" class="btn btn-success" id="confirmLikeBtn">Ya, Like & Latih</button>
      </div>
    </div>
  </div>
</div>

<script>
document.getElementById("confirmLikeBtn").addEventListener("click", async () => {
  const res = await fetch(`/candidates/{{ candidate.id }}/like`, { method: "POST" });
  if (res.ok) {
    bootstrap.Modal.getInstance(document.getElementById("likeConfirmModal")).hide();
    location.reload();
  }
});
</script>
```

Kalau candidate sudah `label_source == "user_liked"`, tampilkan badge
"✓ Liked (training)" dengan link kecil "Batalkan" (panggil endpoint `/unlike`,
TIDAK perlu modal konfirmasi lagi — ini cuma jaga-jaga salah klik, bukan
tindakan yang perlu digembok dua kali).

## Task 4 — Bulk CSV Import untuk 100+ Clip Anda

Daripada input satu-satu lewat UI, siapkan endpoint bulk untuk clip yang
filenya sudah ada di lokal (atau berupa URL):

```python
@router.post("/training/bulk-import")
async def bulk_import_training(
    file: UploadFile,
    service: TrainingImportService = Depends(get_training_import_service),
):
    """CSV format: source,actual_score
    source boleh path file lokal ATAU URL video.
    Contoh baris: /path/to/clip1.mp4,8.5
                  https://youtu.be/xxxxx,9.0
    """
    rows = await service.parse_csv(file)
    job_ids = service.enqueue_bulk_ingest(rows)  # loop: upload/download -> process-training
    return {"queued": len(job_ids), "job_ids": job_ids}
```

Buat `app/services/training_import_service.py` baru — isinya: parse CSV
(pakai `csv` module bawaan Python, validasi `actual_score` di rentang 0-10),
lalu untuk tiap baris panggil ulang logic yang SUDAH ADA di `VideoService`/
`DownloadService` + `ProcessService.start_job(job_type="training_ingest")` dari
TrainingClip 1 — jangan duplikasi logic upload/download, reuse yang sudah ada.

Proses tiap baris di background thread (pola sudah established), supaya
endpoint langsung balas tanpa nunggu 100 clip selesai diproses satu-satu.
Buat halaman kecil `training_import.html` dengan form upload CSV + tampilkan
progress berapa dari 100 yang sudah selesai (reuse pola polling dari
`job_detail.html`).

## Definisi Selesai

- Migrasi `label_source` berhasil dijalankan.
- Setelah reprocess satu video panjang (`job_type='discovery'`), maksimal
  `MAX_AUTO_NEGATIVES_PER_JOB` candidate baru muncul dengan
  `label_source='auto_rejected'`, `status='rejected'`, `actual_score` terisi
  otomatis (bukan NULL).
- Klik tombol Like di `candidate_detail.html` → muncul modal konfirmasi →
  setelah konfirmasi, candidate ter-update `label_source='user_liked'`,
  `actual_score=8.0` (atau sesuai `LIKED_CLIP_DEFAULT_SCORE`).
- Tombol "Batalkan" like berfungsi tanpa modal, mengembalikan candidate ke
  kondisi bukan training example.
- Upload CSV berisi minimal 5 baris test → semua ter-proses di background,
  masing-masing menghasilkan 1 candidate dengan `label_source='real_performance'`
  dan `actual_score` sesuai isi CSV.
