# Database Schema — AI Auto Clipper

Skema **terimplementasi** (SQLAlchemy model di `app/models/`, dikelola lewat Alembic migration di `alembic/versions/`).
Pipeline: `Upload → Extract → Transcribe → Analyze → Score → Generate → Export`, plus History, Cache,
Kategori, dan Training model.

---

## 1. Prinsip Desain

- **Satu tabel generik `analysis_results`** untuk menampung output SEMUA analyzer (voice, face, gesture, scene, hook, LLM, dst), bukan satu tabel per analyzer. Alasan: konsisten dengan `ai_modules/` yang plugin-ready — menambah analyzer baru tidak perlu migrasi tabel baru, cukup `analyzer_type` baru + isi `result_data` (JSONB) sesuai kebutuhannya.
- **`jobs` + `job_steps`** memisahkan "satu kali proses video" dari "riwayat tiap tahap pipeline" — dipakai Monitoring.
- **`candidates` vs `clips`** dipisah: `candidates` = hasil Score Engine & Candidate Generator (kandidat sebelum dipilih), `clips` = hasil akhir setelah Render/Export (bisa 1 candidate → beberapa clip, mis. versi 9:16 dan 1:1).
- **Kategori (`categories`)** dipakai untuk mengelompokkan konten (Gaming, Podcast, dsb) — `candidates`, `jobs`, dan `training_runs` punya FK `category_id`.
- **`training_runs`** menyimpan riwayat training model per kategori (tidak menimpa), plus pointer file model + metrik validasi.
- Semua tabel punya `created_at`; tabel yang bisa berubah status punya `updated_at`.

---

## 2. Daftar Tabel

### `videos`
Video sumber (hasil upload atau download).

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| original_filename | TEXT | nama file asli saat upload |
| source_type | TEXT | `upload` \| `download` |
| source_url | TEXT NULL | jika dari downloader |
| file_path | TEXT | lokasi di `data/uploads/` |
| duration_seconds | FLOAT NULL | diisi setelah metadata diekstrak |
| width | INTEGER NULL | |
| height | INTEGER NULL | |
| fps | FLOAT NULL | |
| file_size_bytes | INTEGER NULL | |
| status | TEXT | `uploaded` \| `processing` \| `ready` \| `failed` |
| is_archived | BOOLEAN | arsip (soft-delete) |
| archived_at | DATETIME NULL | |
| created_at | DATETIME | |
| updated_at | DATETIME | |

### `jobs`
Satu kali eksekusi pipeline untuk satu video.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| video_id | INTEGER FK → videos.id | |
| category_id | INTEGER FK → categories.id NULL | kategori konten (ondelete SET NULL) |
| pipeline_name | TEXT | mis. `auto_clipper_v1` |
| status | TEXT | `pending` \| `running` \| `completed` \| `failed` |
| job_type | TEXT | `discovery` \| `training_ingest` |
| current_step | TEXT NULL | step yang sedang/terakhir jalan |
| started_at | DATETIME NULL | |
| finished_at | DATETIME NULL | |
| error_message | TEXT NULL | |
| created_at | DATETIME | |

### `job_steps`
Riwayat per-tahap dalam satu job (dipakai Monitoring & performance.log correlation).

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| job_id | INTEGER FK → jobs.id | |
| step_name | TEXT | `extract` \| `transcribe` \| `analyze` \| `score` \| `generate` \| `export` |
| status | TEXT | `pending` \| `running` \| `success` \| `failed` |
| started_at | DATETIME NULL | |
| finished_at | DATETIME NULL | |
| duration_ms | INTEGER NULL | |
| error_message | TEXT NULL | |

### `transcripts`
Hasil Speech-to-Text per video/job.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| video_id | INTEGER FK → videos.id | |
| job_id | INTEGER FK → jobs.id | |
| engine | TEXT | mis. `whisper-large-v3` |
| language | TEXT NULL | |
| full_text | TEXT | gabungan seluruh transcript |
| created_at | DATETIME | |

### `transcript_segments`
Potongan transcript per-kalimat/per-waktu (dasar untuk subtitle & keyword detection).

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| transcript_id | INTEGER FK → transcripts.id | |
| speaker_id | INTEGER FK → speakers.id NULL | |
| start_time | FLOAT | detik |
| end_time | FLOAT | detik |
| text | TEXT | |
| confidence | FLOAT NULL | |

### `speakers`
Hasil Speaker Detection, per video.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| video_id | INTEGER FK → videos.id | |
| label | TEXT | mis. `Speaker 1` |
| created_at | DATETIME | |

### `analysis_results` (generik, plugin-ready)
Output semua analyzer: voice, face, gesture, scene, keyword, hook, LLM, dst.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| video_id | INTEGER FK → videos.id | |
| job_id | INTEGER FK → jobs.id | |
| analyzer_type | TEXT | `voice` \| `face` \| `gesture` \| `scene` \| `keyword` \| `hook` \| `llm` \| ... |
| start_time | FLOAT NULL | null jika hasil scope seluruh video |
| end_time | FLOAT NULL | |
| score | FLOAT NULL | skor mentah dari analyzer ini (sebelum digabung Score Engine) |
| result_data | JSONB | payload spesifik analyzer, bebas skema |
| created_at | DATETIME | |

### `candidates`
Hasil Score Engine + Candidate Generator — kandidat klip sebelum di-render.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| video_id | INTEGER FK → videos.id | |
| job_id | INTEGER FK → jobs.id | |
| category_id | INTEGER FK → categories.id NULL | kategori yang ditandai user (ondelete SET NULL) |
| start_time | FLOAT | |
| end_time | FLOAT | |
| final_score | FLOAT | skor gabungan |
| score_breakdown | JSONB | kontribusi tiap analyzer ke final_score |
| hook_text | TEXT NULL | cuplikan teks hook yang terdeteksi |
| status | TEXT | `candidate` \| `selected` \| `rejected` |
| actual_score | FLOAT NULL | skor label training (dari CSV / kategori user) |
| is_training_example | BOOLEAN | true = dipakai data training |
| label_source | TEXT NULL | `real_performance` \| `user_liked` \| `user_disliked` |
| created_at | DATETIME | |

### `clips`
Hasil akhir Render/Export Engine — file klip jadi.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| candidate_id | INTEGER FK → candidates.id NULL | |
| video_id | INTEGER FK → videos.id | |
| file_path | TEXT | lokasi di `data/outputs/` |
| start_time | FLOAT | |
| end_time | FLOAT | |
| aspect_ratio | TEXT | mis. `9:16`, `1:1` (hasil Auto Reframe) |
| has_subtitle | BOOLEAN | |
| status | TEXT | `rendering` \| `completed` \| `failed` |
| exported_at | DATETIME NULL | |
| created_at | DATETIME | |

### `subtitles`
Subtitle per clip (bisa multi-bahasa/multi-format).

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| clip_id | INTEGER FK → clips.id | |
| format | TEXT | `srt` \| `vtt` |
| language | TEXT | |
| file_path | TEXT | |
| created_at | DATETIME | |

### `history`
Audit trail lintas video/job (dasar History Module & Replay Analysis).

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| video_id | INTEGER FK → videos.id NULL | |
| job_id | INTEGER FK → jobs.id NULL | |
| action | TEXT | mis. `video_uploaded`, `pipeline_started`, `clip_exported` |
| description | TEXT NULL | |
| created_at | DATETIME | |

### `cache_entries`
Metadata cache hasil antara (file besar tetap di `data/cache/`, tabel ini index-nya).

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| cache_key | TEXT UNIQUE | mis. `video:12:transcribe` |
| video_id | INTEGER FK → videos.id NULL | |
| step_name | TEXT NULL | |
| file_path | TEXT NULL | |
| expires_at | DATETIME NULL | |
| created_at | DATETIME | |

### `categories`
Kategori clip style yang dibuat user (Gaming, Podcast, dsb) — basis isolasi model training.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| name | VARCHAR(100) UNIQUE | nama kategori |
| created_at | DATETIME | |
| updated_at | DATETIME | |

### `training_runs`
Riwayat eksekusi training model per kategori (tidak menimpa run lama).

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| trained_at | DATETIME | waktu training |
| category_id | INTEGER FK → categories.id | kategori run ini |
| sample_count | INTEGER | jumlah contoh training |
| real_performance_count | INTEGER | contoh dari label `real_performance` (CSV) |
| user_liked_count | INTEGER | contoh dari label kategori user |
| auto_rejected_count | INTEGER | (legacy, selalu 0 sejak dislike tidak jadi training) |
| val_mae | FLOAT | MAE validasi |
| val_r2 | FLOAT | R² validasi |
| feature_importance | JSONB | pentingnya tiap feature model |
| model_file_path | TEXT | path ke `data/models/category_{id}/versions/score_model_{ts}.pkl` |
| is_active | BOOLEAN | model aktif kategori ini (maks 1 per kategori) |
| created_at | DATETIME | |
| updated_at | DATETIME | |

---

## 3. Relasi (ERD ringkas)

```
categories 1───N jobs
categories 1───N candidates
categories 1───N training_runs
videos 1───N jobs 1───N job_steps
videos 1───N transcripts 1───N transcript_segments N───1 speakers
videos 1───N speakers
videos 1───N analysis_results
videos 1───N candidates 1───N clips 1───N subtitles
videos 1───N history        jobs 1───N history
videos 1───N cache_entries
```

---

## 4. Kenapa Bukan Satu Tabel per Analyzer

Kalau tiap analyzer (`voice_analysis`, `face_analysis`, `gesture_analysis`, dst) punya tabel sendiri, setiap kali menambah analyzer baru (mis. Music Analyzer, OCR sesuai rencana Anda) butuh migrasi skema baru — bertentangan dengan prinsip plugin-ready yang sudah disepakati di `ai_modules/`. Dengan `analysis_results` generik + kolom `result_data` JSONB, analyzer baru cukup daftar `analyzer_type` baru tanpa migrasi. Konsekuensinya: query spesifik per analyzer_type sedikit lebih kerja (filter via operator JSONB/`->>`), tapi ini trade-off yang wajar untuk fase MVP — bisa dipecah ke tabel khusus nanti kalau salah satu analyzer butuh query kompleks (mis. face bounding box per frame).

---

Implementasi: SQLAlchemy model di `app/models/`, skema dikelola via Alembic migration (`alembic upgrade head`).
