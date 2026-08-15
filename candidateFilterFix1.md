# Candidate Filter Fix 1 — Sembunyikan `training_ingest` dari Candidate Clips

Konteks: halaman "Candidate Clips" (`/candidates` dan `/candidates/video/{id}`)
menampilkan SEMUA candidate tanpa peduli asalnya — termasuk yang dari upload
CSV training (`job_type="training_ingest"`). Padahal data training itu cuma
untuk melatih model scoring, bukan untuk direview/di-generate jadi clip
seperti alur normal. Filter berdasarkan `job_type` di titik query-nya.

## Task 1 — Filter `get_video_summaries()`

Di `app/services/candidate_service.py`:

```python
def get_video_summaries(self) -> list[dict]:
    """Return per-video summary: video info + candidate counts + top score.

    Candidate dari job_type="training_ingest" DIKECUALIKAN — itu data
    training, bukan candidate untuk direview/di-generate lewat alur normal.
    """
    from app.models.video_model import VideoModel
    from app.models.job_model import JobModel

    videos = self.db.query(VideoModel).order_by(VideoModel.id.desc()).all()
    result = []
    for video in videos:
        candidates = (
            self.db.query(CandidateModel)
            .join(JobModel, CandidateModel.job_id == JobModel.id)
            .filter(
                CandidateModel.video_id == video.id,
                JobModel.job_type != "training_ingest",
            )
            .all()
        )
        if not candidates:
            continue
        # ... sisa logic (top_score, liked, disliked, clips_done) TIDAK BERUBAH
```

## Task 2 — Filter `list_by_video()`

```python
def list_by_video(self, video_id: int) -> list[CandidateModel]:
    """Return all candidates for a specific video, sorted by score desc.

    Candidate dari job_type="training_ingest" DIKECUALIKAN (sama seperti
    get_video_summaries) — kalau video ini murni video training, hasilnya
    akan list kosong, dan router akan tampilkan pesan "belum ada candidates"
    (bukan error).
    """
    from app.models.job_model import JobModel

    candidates = list(
        self.db.query(CandidateModel)
        .join(JobModel, CandidateModel.job_id == JobModel.id)
        .filter(
            CandidateModel.video_id == video_id,
            JobModel.job_type != "training_ingest",
        )
        .order_by(CandidateModel.final_score.desc())
        .all()
    )
    for c in candidates:
        self.db.refresh(c)
    return candidates
```

## Task 3 — Cek Konsisten dengan Halaman Lain

Pastikan halaman yang MEMANG sengaja menampilkan training data (Training
Dashboard, `training_stats_service.py`) **TIDAK ikut difilter** — dia harus
tetap baca berdasarkan `is_training_example=True`, bukan lewat method yang
baru saja diubah ini. Cek `training_stats_service.py` TIDAK memanggil
`get_video_summaries()`/`list_by_video()` (kemungkinan besar dia punya query
sendiri) — kalau ternyata ada dependency ke situ, JANGAN diubah, method yang
diubah cuma di file `candidate_service.py`.

## Definisi Selesai

- Upload CSV training baru (atau cek video training yang sudah ada) → video
  itu **TIDAK muncul** di halaman `/candidates`.
- Coba akses langsung `/candidates/video/{id}` untuk video training (kalau
  tahu ID-nya) → tampil pesan "Belum ada candidates untuk video ini", bukan
  daftar candidate training-nya.
- Video yang diproses normal (job_type `discovery`) tetap muncul seperti
  biasa di `/candidates` — tidak ada regresi.
- Buka `/training/dashboard` → jumlah training example (real_performance,
  user_liked, auto_rejected) **tetap sama** seperti sebelum perubahan ini —
  bukti perubahan ini cuma soal tampilan browsing, bukan menghapus data.
