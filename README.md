# AI Auto Clipper

Tool lokal AI untuk mengekstrak klip viral dari video panjang (YouTube, podcast, interview). Pipeline: upload/download → transcribe (Whisper) → analisis multi-analyzer → scoring → pilih candidate → render clip + subtitle + **Auto Hook** (cold-open teaser).

**Stack:** Python 3.14 · FastAPI · PostgreSQL · FFmpeg · Faster-Whisper · OpenAI-compatible LLM

## Fitur Utama

- ✅ Sliding window menyapu seluruh video, scoring + candidate terbaik
- ✅ 8 analyzer: LLM content, face emotion, voice, gesture, eye contact, scene, audio, hook/story
- ✅ Render clip 9:16 / 16:9 / 1:1 + subtitle SRT/VTT
- ✅ **Auto Hook Engine** — potongan pembuka 1–5 detik dari momen paling menarik di dalam clip (teaser zoom + caption overlay + whoosh SFX), lalu concat ke full clip. Butuh LLM. Gagal hook = clip normal tetap dipakai (tak pernah ngerusak hasil).
- ✅ Training model scoring per kategori
- ✅ YouTube download + penanganan anti-bot

## Prasyarat

| Tool | Versi | Catatan |
|------|-------|---------|
| Python | 3.14+ | wajib, dependency pin ke 3.14 |
| PostgreSQL | 16 | koneksi via `DATABASE_URL` |
| FFmpeg + ffprobe | apa saja | set path di `.env` kalau tidak di PATH |
| Node.js | 18+ | **wajib** untuk download YouTube |
| 9Router (opsional) | npm global | proxy LLM lokal, lihat di bawah |

## Setup (5 langkah)

```bash
# 1. Clone & masuk folder
git clone <repo-url>
cd ai-auto-clipper

# 2. Virtual env + install
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt

# 3. Konfigurasi .env
cp .env.example .env

# 4. Migrasi database (PostgreSQL harus jalan dulu)
alembic upgrade head

# 5. Jalankan
uvicorn app.main:app --reload
```

Buka **http://127.0.0.1:8000**

## Konfigurasi LLM

Semua fitur LLM (scoring content + Auto Hook) pakai API OpenAI-compatible lewat `LLM_BASE_URL`.

**Opsi A — 9Router (proxy lokal gratis, direkomendasikan):**
```bash
npm install -g 9router
9router
# dashboard: http://localhost:20128/dashboard
```
```env
LLM_MODEL=DABOJI
LLM_API_KEY=sk-<key dari 9router>
LLM_BASE_URL=http://localhost:20128/v1
```

**Opsi B — provider langsung (OpenAI/Anthropic/Gemini proxied):**
```env
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
```

**Tanpa LLM / key kosong:** scoring pakai mock (netral), Auto Hook otomatis skip.

## Auto Hook (ringkas)

Saat *Generate Clip*: LLM pilih momen paling menarik di dalam window clip → potong 1–5 detik → zoom-punch + caption jujur (angka wajib dari transkrip asli) + whoosh di potongan → concat di depan full clip. Hasil disimpan di `clip.edited_file_path`.

Catatan kualitas:
- Durasi hook mengikuti momen (bukan kaku 2 detik), berakhir di akhir kalimat.
- Caption faktual — angka yang tidak ada di transkrip otomatis diganti teks asli.
- SFX whoosh: `data/assets/sfx/whoosh.mp3` (opsional, tanpa file = hook tetap jalan).

Nonaktifkan: set `USE_AUTO_HOOK=false` di `.env`.

## Environment Variables (utama)

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| DATABASE_URL | postgresql://app:app@localhost:5432/ai_auto_clipper | koneksi PostgreSQL |
| LLM_API_KEY | (kosong) | key LLM — kosong = mock + hook skip |
| LLM_MODEL | gpt-4o-mini | model LLM |
| LLM_BASE_URL | https://api.openai.com/v1 | base URL OpenAI-compatible |
| WHISPER_MODEL | large-v3 | base / small / large-v3 (small = cepat) |
| WHISPER_DEVICE | auto | auto / cuda / cpu |
| FFMPEG_PATH · FFPROBE_PATH | ffmpeg · ffprobe | path binary |
| USE_AUTO_HOOK | true | auto hook aktif/nonaktif |
| AUTO_HOOK_MIN_CONFIDENCE | 0.6 | threshold confidence LLM untuk hook |
| AUTO_HOOK_MIN_WINDOW_SECONDS | 20.0 | min durasi window agar hook dicoba |

Model Whisper & CV (MediaPipe) di-download otomatis saat pertama dipakai.

## Testing

```bash
.venv\Scripts\pytest          # Windows
pytest                        # macOS/Linux
```
Unit test mock semua dependency berat — tidak butuh GPU/FFmpeg/database.

## Troubleshooting

**`parse gagal / Extra data` saat hook** — 9router kadang sisipkan trailing `data: [DONE]` di body HTTP; sudah ditangani otomatis. Kalau masih gagal, restart 9router.

**`Sign in to confirm you're not a bot` (YouTube)** — app sudah coba multi-client + fallback `android`. Coba download ulang.

**`n challenge solving failed`** — Node.js tidak terdeteksi. Pastikan `node --version` jalan.

**`module 'mediapipe' has no attribute 'solutions'`** — pastikan `mediapipe==0.10.35` (Python 3.14 pakai Tasks API, bukan `mp.solutions`).

**`cublas64_12.dll not found`** — install `nvidia-cublas-cu12` (sudah di requirements) atau set `WHISPER_DEVICE=cpu`.

**Koneksi DB gagal** — pastikan PostgreSQL jalan; password berkarakter khusus harus URL-encoded.

## License

MIT