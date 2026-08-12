# TrainingClip 1 — Schema & Whole-Clip Ingestion Mode

Konteks: kita mau menambahkan kemampuan "training clip" — upload clip contoh yang
sudah punya skor performa nyata (dari views/likes, range 7-10), supaya nanti bisa
dipakai melatih model yang menggantikan weighted-sum manual di `score_engine.py`.

Tahap ini HANYA menyiapkan schema database + mode analisis baru untuk clip yang
sudah jadi (bukan raw stream). Belum ada training model, belum ada UI labeling
lengkap — itu di TrainingClip 2 & 3.

## Kenapa Perlu Mode Baru (bukan reuse pipeline apa adanya)

Pipeline normal (`analysis_service._build_windows()`) didesain untuk raw stream
panjang — men-scan banyak window lewat sliding window untuk CARI momen terbaik.
Clip training Anda BEDA: itu sudah berupa "momen terbaik" hasil pilihan orang
(dari views/likes). Jadi yang dibutuhkan bukan "cari window terbaik di dalam clip
ini", tapi "hitung satu feature vector untuk keseluruhan clip ini". Kalau tetap
pakai sliding window, satu clip training bisa pecah jadi 3-5 window terpisah —
tidak jelas yang mana mewakili skor 7-10 yang Anda kasih.

## Task 1 — Tambah Kolom & Job Type

### Migrasi Alembic baru

Tambahkan kolom:

- `jobs.job_type` — VARCHAR, default `'discovery'`. Nilai yang dipakai:
  `'discovery'` (pipeline normal, cari klip dari raw stream — perilaku sekarang)
  atau `'training_ingest'` (mode baru, satu clip → satu feature vector).
- `candidates.actual_score` — FLOAT, nullable. Skor performa nyata (7-10 dari
  views/likes) untuk clip training. NULL untuk candidate hasil pipeline normal.
- `candidates.is_training_example` — BOOLEAN, default `false`. Penanda row ini
  dipakai sebagai data training (baik dari training_ingest maupun nanti
  auto-harvest di TrainingClip 2).

Update `app/models/job_model.py` dan `app/models/candidate_model.py` sesuai
kolom baru (type hint `Mapped[str]` untuk job_type, `Mapped[float | None]` untuk
actual_score, `Mapped[bool]` untuk is_training_example). Jangan lupa jalankan
`alembic revision --autogenerate` lalu review hasilnya sebelum `alembic upgrade head`.

## Task 2 — Mode Whole-Clip di AnalysisService

Di `app/services/analysis_service.py`, method `analyze_job()`, tambahkan
percabangan di awal (sebelum pemanggilan `_build_windows`):

```python
def analyze_job(self, job_id: int, video_id: int, transcript: TranscriptModel, ...):
    job = self.job_service.repo.get(job_id)  # atau ambil job_type dari parameter caller

    segments = self.segment_repo.get_by_transcript(transcript.id)
    if not segments:
        logger.warning("No segments for transcript %d", transcript.id)
        return []

    if job.job_type == "training_ingest":
        # Satu clip = satu window, mencakup seluruh durasi transcript.
        windows = [{
            "start": segments[0].start_time,
            "end": segments[-1].end_time,
            "segments": segments,
        }]
    else:
        windows = self._build_windows(segments, min_dur, max_dur)

    # ... sisa logic (text validator, plugin analyzer, buat candidate) TETAP SAMA,
    # tidak perlu diubah — cuma sumber `windows` yang beda.
```

Pastikan `job_type` bisa diakses di method ini — kalau `JobService` belum expose
getter untuk field ini, tambahkan atau ambil langsung dari objek `job` yang sudah
di-load di awal `analyze_job` (cek kode existing, mungkin sudah ada `job` di scope).

## Task 3 — Endpoint Ingest Training Clip (single clip dulu)

Tambahkan endpoint baru di `app/routers/video_router.py` (atau file baru
`training_router.py` — pilih yang lebih rapi menurut Anda, boleh salah satu):

```python
@router.post("/videos/{video_id}/process-training")
def process_training_clip(
    video_id: int,
    actual_score: float,
    service: ProcessService = Depends(get_process_service),
):
    """Proses video sebagai training clip: whole-clip mode, langsung diberi label.

    Dipakai untuk SATU clip contoh yang sudah dilabel manual (dari views/likes).
    Untuk banyak clip sekaligus, lihat TrainingClip 2 (bulk CSV import).
    """
    if not (0 <= actual_score <= 10):
        raise ValidationException("actual_score harus antara 0-10")
    job = service.start_job(video_id, job_type="training_ingest")
    # setelah pipeline selesai (via background thread seperti biasa), candidate
    # yang dihasilkan (harusnya cuma 1) di-update actual_score + is_training_example
    return {"job_id": job.id, "status": "running"}
```

Sesuaikan dengan pola `start_job`/background-thread yang sudah ada di
`video_router.py` untuk endpoint process biasa — jangan bikin pola baru, ikuti
yang sudah established.

Setelah job `training_ingest` selesai (status completed, exactly 1 candidate
dihasilkan), update candidate itu:

```python
candidate.actual_score = actual_score
candidate.is_training_example = True
self.db.commit()
```

Taruh logic ini di `ProcessService` atau `CandidateService` — bukan di router,
sesuai aturan layering yang sudah kita sepakati sejak awal.

## Definisi Selesai

- Migrasi Alembic berhasil dijalankan, kolom `job_type`, `actual_score`,
  `is_training_example` ada di database.
- Upload 1 video pendek, panggil endpoint `process-training` dengan
  `actual_score=8.5` → setelah selesai, ada tepat 1 row di `candidates` dengan
  `start_time`/`end_time` mencakup seluruh durasi video, `actual_score=8.5`,
  `is_training_example=true`.
- Pipeline normal (`job_type='discovery'`, default) TIDAK berubah perilakunya —
  masih sliding window seperti biasa. Jalankan test yang sudah ada
  (`test_windows_selection.py`) untuk memastikan tidak ada regresi.
