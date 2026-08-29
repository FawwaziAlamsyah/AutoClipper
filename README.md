# AI Auto Clipper

Tool lokal berbasis AI untuk otomatis mengekstrak klip viral dari video panjang (YouTube, podcast, interview, dll). Menjalankan pipeline penuh: upload/download → transcribe (Whisper) → analisis multi-analyzer → scoring → pilih candidate → render clip + subtitle.

**Dibangun dengan:** Python 3.14 + FastAPI + PostgreSQL + FFmpeg + Faster-Whisper + OpenAI-compatible LLM + MediaPipe/OpenCV + librosa + scikit-learn (model scoring per kategori).

> **Catatan versi:** project ini diuji di **Python 3.14** (Windows). Beberapa dependency (mediapipe) punya wheel khusus untuk Python 3.14 yang berbeda perilakunya dari versi lama — lihat [Troubleshooting](#troubleshooting).

## Fitur

- ✅ Upload video lokal atau download dari URL (YouTube, TikTok, dll)
- ✅ Speech-to-text dengan Faster-Whisper (large-v3)
- ✅ 8 analyzer plugin: LLM content, face emotion, voice emotion, gesture, eye contact, scene change, audio quality, hook/story/context/ending (LLM)
- ✅ Weighted scoring engine (bobot 100%) + non-overlap candidate selection
- ✅ **Model scoring per kategori** — tiap kategori (Gaming, Podcast, dsb) punya model terlatih sendiri (scikit-learn GradientBoosting), fallback ke weighted-sum kalau kategori belum dilatih
- ✅ **Training per kategori** — label candidate via dropdown kategori, training di-isolasi per kategori, riwayat run + rollback/aktifkan model per kategori
- ✅ Sliding window menyapu seluruh video (bukan potongan linear)
- ✅ Preview candidate tanpa render penuh
- ✅ Final clip render dengan FFmpeg (9:16 / 16:9 / 1:1)
- ✅ Subtitle generation (SRT/VTT, word-level)
- ✅ Progress tracker realtime per-job step
- ✅ Audit trail & history

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.14+, FastAPI, Jinja2, SQLAlchemy |
| Database | PostgreSQL 16 |
| Audio/Video | FFmpeg, ffprobe, OpenCV, MediaPipe, librosa |
| Speech-to-Text | Faster-Whisper |
| AI | OpenAI-compatible LLM API (default gpt-4o-mini) |
| Download | yt-dlp + curl_cffi + yt-dlp-ejs + Playwright (cookie auto-capture) |
| Frontend | Bootstrap 5, vanilla JS |
| Testing | pytest |

## Prasyarat

1. **Python 3.14+** — [python.org](https://www.python.org/downloads/)
2. **PostgreSQL 16** — [postgresql.org](https://www.postgresql.org/download/) atau Docker:
   ```bash
   docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=yourpass -e POSTGRES_DB=ai_auto_clipper postgres:16-alpine
   ```
3. **FFmpeg + ffprobe** — [ffmpeg.org](https://ffmpeg.org/download.html)
   - Windows: pastikan `ffmpeg` dan `ffprobe` di PATH, atau set `FFMPEG_PATH`/`FFPROBE_PATH` di `.env`
   - macOS: `brew install ffmpeg` | Linux: `sudo apt install ffmpeg`
4. **Node.js 18+** — [nodejs.org](https://nodejs.org/) — **WAJIB** untuk download YouTube (n-challenge solver). Verifikasi: `node --version`.

## Setup Project

```bash
# 1. Clone
git clone https://github.com/yourusername/ai-auto-clipper.git
cd ai-auto-clipper

# 2. Buat & aktivasi venv
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 3b. Install browser Chromium untuk login YouTube otomatis (WAJIB, sekali saja)
playwright install chromium

# 4. Copy .env & isi
cp .env.example .env
```

### Konfigurasi `.env`

Wajib minimal: `DATABASE_URL` (PostgreSQL) dan `LLM_API_KEY` (kalau mau scoring LLM aktif).

```env
DATABASE_URL=postgresql+psycopg://postgres:yourpass@localhost:5432/ai_auto_clipper
LLM_API_KEY=sk-...                # kosong = LLM pakai mock (skor netral)
WHISPER_MODEL=base                # kecil = cepat; large-v3 = akurat tapi butuh GPU
```

Lihat [.env.example](.env.example) untuk semua variabel + default.

### Database Migration

```bash
alembic upgrade head
# atau .venv\Scripts\alembic upgrade head
```

### Menjalankan App

```bash
# --no-access-log: terminal fokus ke log.debug proses, bukan request per-halaman
.\.venv\Scripts\uvicorn app.main:app --reload
# atau .venv\Scripts\uvicorn app.main:app --reload --no-access-log
```

Buka browser: **http://127.0.0.1:8000**

## Model AI (auto-download)

- **Whisper model** — di-download otomatis saat pertama transcribe (cache di `~/.cache/huggingface`). `WHISPER_MODEL` di `.env`.
- **MediaPipe CV models** (face_landmarker, hand_landmarker) — di-download otomatis ke `data/models/` saat pertama analyze.

## Download dari URL (YouTube & anti-bot)

YouTube sering memblokir dengan error `Sign in to confirm you're not a bot`. Project menangani ini berlapis:

1. **Login YouTube sekali klik** (rekomendasi) — di halaman Upload, klik tombol **🔑 Login YouTube (Sekali Saja)**. Jendela Chromium muncul, login manual di sana. Cookies otomatis tersimpan ke `data/cookies.txt`. Tidak perlu export ekstensi.
2. **`COOKIES_FILE`** (alternatif manual) — export cookies login dari browser:
   - Install ekstensi **"Get cookies.txt LOCALLY"** di Chrome
   - Buka `youtube.com`, login, klik ekstensi → **Export** → simpan sebagai `data/cookies.txt`
   - Set `COOKIES_FILE=data/cookies.txt` di `.env`
   - **Penting:** cookies harus dari sesi LOGIN (bukan guest — cek `SID` value tidak berawal `g.a000BAnon`)
3. **Fallback tanpa cookies** — kalau `COOKIES_FILE` kosong/tidak ada, app coba client android lalu web.
4. **Node.js** — wajib terpasang; tanpanya format video disembunyikan (error `n challenge solving failed`).
5. **Playwright Chromium** — wajib untuk tombol login YouTube. Setelah `pip install -r requirements.txt`, jalankan sekali: `playwright install chromium`. Kalau langkah ini kelewat, tombol login akan error saat pertama dipakai.

`data/cookies.txt` dan `data/models/` sudah di-`.gitignore` — tidak akan ter-push.

## Cara Menggunakan

### 1. Upload / Download
- **Upload file:** pilih video lokal (mp4/mov/mkv/avi, maks 2GB).
- **Download URL:** masukkan URL YouTube/TikTok → progress bar persen realtime.

### 2. Atur Pipeline
Bahasa, **kategori** (dropdown, diisi dari halaman Training), jumlah clip, durasi min/max, keyword boost, skip keywords. Setting tersimpan per-session browser (tidak reset saat pindah halaman).

### 3. Proses Pipeline
Tombol **Proses** → job berjalan di background dengan progress step realtime (`extract → transcribe → analyze → score → complete` + 7 sub-step analyzer). Video yang sudah pernah diproses (status `ready`) diminta konfirmasi sebelum diproses ulang.

### 4. Review Candidate
- **Candidates** → tabel skor. Klik **Detail** → breakdown per analyzer (skor + kontribusi), preview video, generate clip.
- **Label training**: pilih kategori dari dropdown di tiap card candidate → tombol ✓ untuk menandai contoh positif kategori itu. Tombol 👎 hanya penanda kualitas (bukan data training).
- Window tersebar di seluruh video (sliding window), top-N dipilih non-overlap.

### 5. Generate Final Clip & Subtitle
- Generate clip (FFmpeg, pilih aspect ratio).
- Generate subtitle (SRT/VTT, style minimal/tiktok/youtube).

### 6. Training Model per Kategori
- **Halaman Training** (`/training`) — buat/rename/hapus kategori, pilih kategori aktif via tombol di dashboard.
- **Data training** — kumpulkan ≥20 contoh per kategori lewat dropdown di candidate grid ATAU bulk CSV import (`/training`, CSV berformat `source,actual_score` + pilihan kategori).
- **Train Model** — klik per kategori, model disimpan ke `data/models/category_{id}/`, riwayat run + metrik (val MAE / R²) per kategori.
- **Aktifkan/Rollback** — pilih run historis kategori tertentu jadi aktif tanpa memengaruhi kategori lain.
- Scoring pakai model terlatih kategori jika ada; kalau belum dilatih/kategori kosong → fallback weighted-sum.

## Struktur Folder

```
ai-auto-clipper/
├── app/
│   ├── ai_modules/          # Analyzer plugin (plugin-ready, registrasi via registry.py)
│   │   ├── base/            #   AnalyzerInterface + AnalysisResult
│   │   ├── registry.py      #   daftar analyzer aktif
│   │   ├── speech_to_text/  #   whisper
│   │   ├── llm_analysis/    #   llm_content (hook/story/context/ending)
│   │   ├── face_analysis/   #   face_emotion, eye_contact
│   │   ├── gesture_analysis/#   gesture
│   │   ├── scene_analysis/  #   scene
│   │   └── voice_analysis/  #   voice_emotion, audio
│   ├── core/                # config, logging (console + error.log), exceptions, DI
│   ├── db/                  # koneksi DB (PostgreSQL)
│   ├── ml/                  # training & prediksi model scoring (feature_builder, trainer, predictor)
│   ├── models/              # SQLAlchemy ORM (termasuk CategoryModel, TrainingRunModel)
│   ├── repositories/        # data access layer
│   ├── schemas/             # Pydantic DTO
│   ├── services/            # business logic (analysis, score, process, category, training, dll)
│   ├── routers/             # FastAPI endpoints (termasuk category_router, training_router)
│   ├── templates/           # Jinja2 HTML
│   ├── static/              # CSS/JS
│   └── main.py
├── alembic/                 # DB migrations
├── data/
│   ├── uploads/             # video input
│   ├── outputs/             # final clips + subtitle
│   ├── cache/               # audio hasil extract
│   ├── models/              # CV .tflite (auto-download, git-ignored) + category_{id}/ model per kategori
│   ├── cookies.txt          # cookies YouTube (git-ignored)
│   └── ...
├── logs/                    # error.log saja (progress di terminal via log.debug)
├── tests/                   # pytest (55 test)
├── .env.example
├── requirements.txt
└── README.md
```

## Menambah Analyzer Baru (plugin-ready)

Tambah analyzer baru **tanpa mengubah pipeline**:

1. Buat `app/ai_modules/<nama>/<nama>_analyzer.py`:
   ```python
   from app.ai_modules.base.analyzer_interface import AnalyzerInterface, AnalysisResult
   from app.ai_modules.registry import register_analyzer

   @register_analyzer
   class XAnalyzer(AnalyzerInterface):
       analyzer_type = "x_type"
       def analyze(self, input):  # input: dict (path video/audio/teks)
           return AnalysisResult(score=8.0, result_data={"reason": "..."})
   ```
2. Import di `app/ai_modules/__init__.py` (agar auto-register).
3. Tambahkan ke `input_builders` di `app/services/analysis_service.py`.
4. Set bobot di `settings.py` (`SCORE_WEIGHT_*`).

`process_service.py` dan orchestration **tidak berubah**.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | postgresql://app:app@localhost:5432/ai_auto_clipper | PostgreSQL connection |
| LLM_API_KEY | (empty) | API key LLM (kosong = mock, skor netral) |
| LLM_MODEL | gpt-4o-mini | Nama model LLM |
| LLM_BASE_URL | https://api.openai.com/v1 | Base URL (OpenAI-compatible) |
| WHISPER_MODEL | large-v3 | Model whisper (base/small/large-v3) |
| WHISPER_DEVICE | auto | auto/cuda/cpu |
| FFMPEG_PATH | ffmpeg | Path FFmpeg binary |
| FFPROBE_PATH | ffprobe | Path ffprobe binary |
| COOKIES_FILE | data/cookies.txt | Cookies YouTube (kosong = cookiesfrombrowser) |
| MAX_UPLOAD_SIZE_MB | 2048 | Max upload size |
| LOG_LEVEL | INFO | Level log |
| USE_TRAINED_SCORE_MODEL | true | Pakai model terlatih per kategori; false = paksa weighted-sum |
| LIKED_CLIP_DEFAULT_SCORE | 8.0 | Skor default candidate yang ditandai contoh positif via kategori |

## Testing

```bash
.venv\Scripts\pytest          # Windows
# pytest                      # macOS/Linux
```

Semua test mock dependency berat (whisper, mediapipe, cv2) — tidak perlu GPU/FFmpeg untuk unit test.

## Troubleshooting

**`Sign in to confirm you're not a bot` (YouTube)**
- Cookies tidak valid/guest. Re-export cookies saat login (cek `SID` tidak berawal `BAnon`), atau coba browser lain.

**`Could not copy Chrome cookie database`**
- Browser target sedang berjalan (DB terkunci). Tutup browser sepenuhnya, atau pakai browser lain.

**`n challenge solving failed: Some formats may be missing`**
- Node.js tidak terdeteksi. Pastikan `node --version` jalan; project force `js_runtimes: {"node": {}}`.

**`module 'mediapipe' has no attribute 'solutions'`**
- Python 3.14 wheel mediapipe hanya punya **Tasks API**, bukan `mp.solutions`. Project sudah pakai Tasks API (`FaceLandmarker`/`HandLandmarker`) — pastikan `mediapipe==0.10.35` (pin di requirements).

**`cublas64_12.dll not found` (GPU whisper)**
- Install `nvidia-cublas-cu12` (sudah di requirements). Kalau tak pakai GPU, set `WHISPER_DEVICE=cpu`.

**Koneksi DB gagal**
- Pastikan PostgreSQL jalan di port 5432. Password berkarakter khusus → URL-encode.

**LLM skor semua netral**
- `LLM_API_KEY` kosong → analyzer llm_content pakai mock. Isi key di `.env`.

## License

MIT License
