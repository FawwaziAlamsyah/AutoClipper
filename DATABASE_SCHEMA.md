# Database Schema Design — AI Auto Clipper

Desain tabel untuk mendukung pipeline: `Upload → Extract → Transcribe → Analyze → Score → Generate → Export`,
plus History & Cache. Ini masih **desain/konsep** — belum diimplementasikan sebagai SQLAlchemy model,
menunggu prompt teknis Anda berikutnya.

---

## 1. Prinsip Desain

- **Satu tabel generik `analysis_results`** untuk menampung output SEMUA analyzer (voice, face, gesture, scene, keyword, hook, LLM), bukan satu tabel per analyzer. Alasan: konsisten dengan `ai_modules/` yang plugin-ready — menambah analyzer baru tidak perlu migrasi tabel baru, cukup `analyzer_type` baru + isi `result_data` (JSONB) sesuai kebutuhannya.
- **`jobs` + `job_steps`** memisahkan "satu kali proses video" dari "riwayat tiap tahap pipeline" — ini yang nanti dipakai Monitoring Module.
- **`candidates` vs `clips`** dipisah: `candidates` = hasil Score Engine & Candidate Generator (kandidat sebelum dipilih), `clips` = hasil akhir setelah Render/Export (bisa 1 candidate → beberapa clip, mis. versi 9:16 dan 1:1).
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
| created_at | DATETIME | |
| updated_at | DATETIME | |

### `jobs`
Satu kali eksekusi pipeline untuk satu video.

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| video_id | INTEGER FK → videos.id | |
| pipeline_name | TEXT | mis. `auto_clipper_v1` |
| status | TEXT | `pending` \| `running` \| `completed` \| `failed` |
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
| start_time | FLOAT | |
| end_time | FLOAT | |
| final_score | FLOAT | skor gabungan |
| score_breakdown | JSONB | kontribusi tiap analyzer ke final_score |
| hook_text | TEXT NULL | cuplikan teks hook yang terdeteksi |
| status | TEXT | `candidate` \| `selected` \| `rejected` |
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

---

## 3. Relasi (ERD ringkas)

```
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

Belum diimplementasikan sebagai kode (SQLAlchemy model). Beri tahu saya kapan siap, atau lanjutkan dulu prompt teknis berikutnya.
