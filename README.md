# AI Auto Clipper

Tool lokal berbasis AI untuk otomatis mengextract klip viral dari video panjang (YouTube, Podcast, Interview, dll).
Menggunakan Python + FastAPI + PostgreSQL + FFmpeg + Whisper + LLM.

## Fitur

- ✅ Upload video lokal atau download dari URL (YouTube, TikTok, dll)
- ✅ Transcription otomatis dengan Whisper (Faster-Whisper)
- ✅ Analisis video dengan LLM (OpenAI/GPT)
- ✅ Video analysis (FFmpeg metadata extraction)
- ✅ Score engine dengan weighted scoring
- ✅ Candidate clip generation & selection
- ✅ Preview candidate tanpa render
- ✅ Final clip generation dengan FFmpeg
- ✅ Subtitle generation (SRT/VTT)
- ✅ Audit trail & history

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12+, FastAPI, Jinja2 |
| Database | PostgreSQL 16 |
| Audio/Video | FFmpeg, ffprobe |
| Speech-to-Text | Faster-Whisper |
| AI | OpenAI API (LLM), optional yt-dlp |
| Frontend | Bootstrap 5, vanilla JS |
| Testing | pytest |

## Installasi

### Prasyarat

1. **Python 3.12+**  
   Download dari [python.org](https://www.python.org/downloads/)

2. **PostgreSQL 16**  
   Download dari [postgresql.org](https://www.postgresql.org/download/)  
   Atau gunakan Docker: `docker run -p 5432:5432 -e POSTGRES_PASSWORD=yourpass postgres:16-alpine`

3. **FFmpeg**  
   Windows: Download dari [ffmpeg.org](https://ffmpeg.org/download.html)  
   macOS: `brew install ffmpeg`  
   Linux: `sudo apt install ffmpeg`

### Setup Project

```bash
# Clone repository
git clone https://github.com/yourusername/ai-auto-clipper.git
cd ai-auto-clipper

# Buat dan aktivasi virtual environment
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### Konfigurasi Database

Edit file `.env`:

```env
DATABASE_URL=postgresql+psycopg://username:password@localhost:5432/ai_auto_clipper
```

Jika pakai Docker, user/password default:
```
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/ai_auto_clipper
```

### Jalankan Migration

```bash
alembic upgrade head
.\.venv\Scripts\alembic upgrade head #(kalau tidak punya alembic di global)
```

### Jalankan Aplikasi

```bash
# --no-access-log: matikan access log per-request agar terminal fokus
# pada log.debug proses (download process, analyze process, dst).
uvicorn app.main:app --reload --no-access-log
.\.venv\Scripts\uvicorn app.main:app --reload --no-access-log #(kalau tidak punya uvicorn di global)
```

Buka browser: `http://127.0.0.1:8000`

## Cara Menggunakan

### 1. Upload Video
- Buka halaman upload
- Pilih file video lokal (mp4/mov/mkv/avi), maks 2GB
- Atau masukkan URL YouTube/TikTok

### 2. Configure Pipeline
Setelah upload, Anda bisa:
- Pilih bahasa transcription
- Tentukan durasi klip (min/max)
- Tentukan jumlah klip yang diinginkan
- Masukkan content type (podcast/interview/gaming/dll)
- Pilih clip style (viral/educational/funny/dll)
- Masukkan keyword boost/skip keywords

### 3. Proses Pipeline
Pipeline otomatis menjalankan:
1. Extract metadata video (FFmpeg)
2. Extract audio
3. Transcribe (Whisper)
4. LLM analysis (content scoring)
5. Score aggregation
6. Candidate generation

### 4. Preview & Select
- Lihat daftar candidate clips dengan skor
- Preview tiap kandidat (tanpa render penuh)
- Pilih mana yang ingin di-render final

### 5. Generate Final Clip
- Klik "Generate" pada candidate terpilih
- Pilih aspect ratio (9:16, 16:9, 1:1)
- Enable/disable subtitle
- Tunggu proses FFmpeg rendering
- Download hasil akhir

## Struktur Folder

```
ai-auto-clipper/
├── app/
│   ├── core/              # config, logging, exceptions, DI
│   ├── db/                # database connection
│   ├── models/            # SQLAlchemy ORM
│   ├── repositories/      # data access layer
│   ├── schemas/           # Pydantic DTO
│   ├── services/          # business logic
│   ├── routers/           # API endpoints
│   ├── middleware/        # logging, timing
│   ├── templates/         # Jinja2 HTML
│   ├── static/            # CSS/JS
│   └── main.py
├── data/
│   ├── uploads/           # video input
│   ├── outputs/           # final clips
│   ├── cache/             # intermediate results
│   └── temp/
├── logs/
│   ├── app.log
│   ├── error.log
│   └── performance.log
├── alembic/               # DB migrations
├── tests/
├── .env
├── .env.example
├── requirements.txt
└── README.md
```

## Testing

```bash
.venv\Scripts\pytest
```

## Development

### Tambah Model/Service Baru

Ikuti clean architecture pattern:
1. `models/<name>_model.py`
2. `repositories/<name>_repository.py`
3. `schemas/<name>_schema.py`
4. `services/<name>_service.py`
5. `routers/<name>_router.py`

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | postgresql://app:app@localhost:5432/ai_auto_clipper | PostgreSQL connection |
| FFMPEG_PATH | ffmpeg | Path to FFmpeg binary |
| WHISPER_MODEL | large-v3 | Whisper model name |
| LLM_MODEL | gpt-4o-mini | OpenAI model name |
| LLM_API_KEY | (empty) | OpenAI API key |
| MAX_UPLOAD_SIZE_MB | 2048 | Max upload size |
| LOG_LEVEL | INFO | Logging level |

## Troubleshooting

**Error koneksi database:**
- Pastikan PostgreSQL berjalan di port 5432
- Cek `DATABASE_URL` di `.env`
- Untuk password dengan karakter khusus, URL-encode

**FFmpeg not found:**
- Tambahkan path FFmpeg ke PATH Windows
- Atau set `FFMPEG_PATH` di `.env`

**Whisper lambat:**
- Gunakan model lebih kecil: `base` atau `small`
- Pastikan CUDA tersedia jika pakai GPU

## License

MIT License
