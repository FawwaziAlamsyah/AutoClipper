# AI Auto Clipper — Project Foundation

Tech stack: Python 3.12+, FastAPI, Jinja2, Bootstrap, PostgreSQL, Pydantic Settings, `logging`, pytest.
Tahap ini **hanya fondasi** — belum ada fitur AI/FFmpeg/Whisper/Auto Clipper.

---

## 1. Struktur Folder

```
ai-auto-clipper/
├── app/
│   ├── main.py                     # FastAPI app factory, register router & middleware
│   │
│   ├── core/                       # cross-cutting concern, dipakai semua layer
│   │   ├── config/
│   │   │   └── settings.py         # Pydantic Settings, sumber tunggal konfigurasi
│   │   ├── logging/
│   │   │   └── logger.py           # setup 3 handler: app/error/performance
│   │   ├── exceptions/
│   │   │   ├── base.py             # hierarki custom exception
│   │   │   └── handlers.py         # global exception handler utk FastAPI
│   │   ├── di/
│   │   │   └── dependencies.py     # provider untuk FastAPI Depends()
│   │   └── security/               # placeholder future auth (kosong sekarang)
│   │
│   ├── routers/                    # Controller — HTTP endpoint saja
│   │   └── health_router.py        # satu-satunya router di tahap fondasi
│   │
│   ├── schemas/                    # Pydantic DTO utk request/response HTTP
│   │
│   ├── services/                   # business logic / use case orchestration
│   │
│   ├── repositories/                # abstraksi akses data (Repository Pattern)
│   │   ├── base_repository.py       # interface/abstract repository
│   │   └── postgres/                # implementasi konkret utk PostgreSQL
│   │
│   ├── models/                      # SQLAlchemy ORM model — representasi tabel DB
│   │
│   ├── middleware/                  # request logging, error catching, timing
│   │
│   ├── db/
│   │   ├── session.py               # DB session/engine factory
│   │   └── base.py                  # Base declarative + metadata
│   │
│   ├── templates/                   # Jinja2 HTML
│   └── static/                      # css/js, Bootstrap
│
├── data/
│   ├── uploads/                     # file masuk dari user (belum dipakai fase ini)
│   ├── outputs/                     # hasil akhir proses (belum dipakai)
│   ├── cache/                       # hasil antara yang bisa dihitung ulang
│   ├── history/                     # rekam jejak proses/job
│   └── temp/                        # file sementara, aman dihapus kapan saja
│
├── logs/
│   ├── app.log
│   ├── error.log
│   └── performance.log
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
├── alembic/                         # placeholder migrasi DB (future)
├── .env
├── .env.example
├── pyproject.toml
└── README.md
```

Catatan: struktur ini memakai `app/` sebagai package utama (konvensi umum FastAPI), sedangkan `data/` dan `logs/` diletakkan di root — bukan di dalam `app/` — karena keduanya adalah *runtime artifact*, bukan source code, dan harus mudah di-`.gitignore` serta gampang dipindah ke volume terpisah saat nanti pakai Docker.

---

## 2. Fungsi Setiap Folder

| Folder | Tugas | Boleh Disimpan | Tidak Boleh Disimpan |
|---|---|---|---|
| `core/config/` | Sumber tunggal semua konfigurasi | `Settings` class, default value, definisi env var | Nilai rahasia hardcoded, logic bisnis |
| `core/logging/` | Setup logger & handler | Konfigurasi formatter/handler | Pemanggilan `logger.info()` dari business logic (itu tugas module lain) |
| `core/exceptions/` | Hierarki exception & handler global | Custom exception class, mapping exception→HTTP status | Try/except spesifik satu fitur |
| `core/di/` | Definisi provider untuk dependency injection | Fungsi `get_xxx_service()` | Business logic |
| `routers/` | Terima HTTP request, panggil service, kembalikan response | Endpoint, validasi request dasar (via schema) | Query DB langsung, business logic, akses file sistem |
| `schemas/` | Kontrak data masuk/keluar API | Pydantic model request/response | Logic, query DB |
| `services/` | Orkestrasi business logic, use case | Logic aplikasi, pemanggilan repository | Kode HTTP (`Request`/`Response` FastAPI), SQL mentah |
| `repositories/` | Abstraksi akses data | Query DB, CRUD | Business rule, validasi domain |
| `models/` | Representasi tabel database | Kolom, relasi SQLAlchemy | Logic, validasi input user |
| `middleware/` | Proses lintas-request | Logging request, timing, catch exception | Business logic spesifik fitur |
| `db/` | Koneksi & sesi database | Engine, session factory | Query bisnis |
| `templates/` & `static/` | Presentasi UI | HTML, CSS, JS | Logic Python |
| `data/uploads`, `outputs`, `cache`, `history`, `temp` | Runtime file storage | File hasil proses sesuai namanya | Source code, kredensial |
| `logs/` | Output logging | File log | Data user, file besar (video) |
| `tests/` | Pengujian | Unit & integration test | Kode produksi |

---

## 3. Dependency Flow

```
Router  →  Service  →  Repository  →  Storage (DB / File System)
   ↓            ↓             ↓
schemas    (tidak boleh    models
           balik ke atas)
```

Aturan **boleh**:
- Router boleh memanggil Service (lewat DI, bukan instansiasi langsung).
- Service boleh memanggil satu atau lebih Repository.
- Repository boleh mengakses `models/` dan `db/session.py`.
- Semua layer boleh memakai `core/` (config, logging, exceptions).

Aturan **tidak boleh**:
- Router **tidak boleh** memanggil Repository atau `db/` langsung — harus lewat Service. Ini mencegah "fat controller" dan menjaga business logic tetap testable tanpa HTTP.
- Service **tidak boleh** mengenal FastAPI (`Request`, `Response`, `HTTPException`) — Service harus bisa dipanggil dari CLI/test tanpa web server.
- Repository **tidak boleh** berisi business rule (mis. validasi skor, keputusan bisnis) — hanya operasi data mentah.
- Layer bawah (`repositories`, `models`) **tidak boleh** memanggil layer atas (`services`, `routers`) — dependency selalu satu arah ke bawah.

---

## 4. Coding Convention

| Elemen | Konvensi | Contoh |
|---|---|---|
| Nama file | `snake_case`, diakhiri sesuai peran | `video_service.py`, `video_repository.py`, `video_router.py`, `video_model.py`, `video_schema.py` |
| Nama class | `PascalCase`, diakhiri sesuai peran | `VideoService`, `VideoRepository`, `VideoModel`, `VideoCreateSchema` |
| Nama router | `PascalCase` + `Router`, prefix di `main.py` | `HealthRouter` → `/health` |
| Nama service | Nama domain + `Service` | `VideoService`, `HistoryService` |
| Nama config | `Settings`, field `UPPER_SNAKE_CASE` di `.env` | `DATABASE_URL`, `LOG_LEVEL` |
| Function/variable | `snake_case` | `get_video_by_id()` |
| Type hint | Wajib di semua public function/method | `def get(self, video_id: int) -> Video \| None:` |
| Docstring | Wajib untuk class & public method, gaya Google-style | `"""Ambil video berdasarkan ID."""` |
| Logging | `logger = logging.getLogger(__name__)` per modul, tidak pernah pakai `print()` | — |

---

## 5. Configuration System

- `app/core/config/settings.py` berisi class `Settings(BaseSettings)` dari **Pydantic Settings**, membaca dari `.env`.
- `.env.example` didaftarkan di repo (tanpa nilai rahasia); `.env` asli di-`.gitignore`.
- Urutan prioritas nilai: default di `Settings` → `.env` → environment variable OS (paling tinggi).
- Semua module lain mengambil config lewat `from app.core.config.settings import settings` — **tidak ada hardcode** path, nama file, atau parameter di module manapun.
- Contoh field tahap fondasi: `APP_NAME`, `APP_ENV`, `DATABASE_URL`, `LOG_LEVEL`, `LOG_DIR`, `DATA_DIR`.

---

## 6. Logging Architecture (Konsep, Belum Implementasi)

Tiga file log terpisah berdasarkan tujuan, bukan berdasarkan modul:

| File | Isi | Level |
|---|---|---|
| `app.log` | Alur normal aplikasi (start up, request masuk, proses selesai) | INFO ke atas |
| `error.log` | Exception & error saja, termasuk traceback | ERROR ke atas |
| `performance.log` | Durasi eksekusi (nanti: durasi tiap step pipeline) | INFO khusus metrik |

Konsep: satu `logger` per modul (`__name__`), tapi **handler** yang menentukan file tujuan berdasarkan level/kategori — bukan tiap modul menulis ke file manual. Format log terstruktur (timestamp, level, module, message, opsional request-id) supaya mudah di-parse nanti oleh Monitoring Module.

---

## 7. Error Handling (Konsep, Belum Implementasi)

- Hierarki: `AppException` (base) → turunan spesifik seperti `NotFoundException`, `ValidationException`, `ExternalToolException` (dipakai nanti oleh FFmpeg/Whisper module).
- Global exception handler didaftarkan di `main.py`, memetakan tiap jenis exception ke HTTP status code yang sesuai (404, 422, 500, dst).
- Semua exception tak terduga tertangkap di satu tempat, dicatat ke `error.log` dengan traceback, dan direspons ke user dalam format seragam — tidak ada `try/except` yang menyembunyikan error secara diam-diam di router.

---

## 8. Kesiapan untuk Module Masa Depan

Setiap module baru (Upload, Download, FFmpeg, Whisper, OpenCV, LLM, Scoring, Subtitle, History, Monitoring, Replay) mengikuti pola yang sama tanpa mengubah struktur inti:

```
routers/<module>_router.py        (opsional, jika perlu endpoint sendiri)
schemas/<module>_schema.py
services/<module>_service.py
repositories/<module>_repository.py   (jika perlu akses data sendiri)
models/<module>_model.py              (jika perlu tabel baru)
```

Module berat seperti FFmpeg/Whisper/OpenCV nantinya diletakkan di sub-service tersendiri (mis. `services/processing/ffmpeg_service.py`) yang dipanggil oleh service orkestrasi level lebih tinggi — tanpa mengubah `routers/` maupun `core/`.

---

## 9. MVC vs Clean/Layered Architecture

Pemetaan kasar ke MVC:
- **Model** ≈ `models/` + `schemas/`
- **View** ≈ `templates/` + `static/`
- **Controller** ≈ `routers/`

MVC murni memaksa Controller memanggil Model langsung — cukup untuk CRUD sederhana, tapi project ini akan punya proses berat (transcribe, analisis, scoring) yang bukan sekadar baca/tulis DB. Karena itu digunakan **MVC + Service Layer**, yang secara efektif menjadi **Layered Architecture**: Router tidak pernah menyentuh Model/DB langsung, semua lewat Service. Ini memberi tempat yang jelas untuk business logic dan proses AI di masa depan, serta membuat logic tersebut testable tanpa perlu menjalankan web server.

---

## 10. Best Practice & Potensi Masalah

**Best practice:**
- Router setipis mungkin: validasi via schema, panggil satu service, return.
- Satu Service tidak memanggil Service lain secara berantai panjang — jika perlu, buat use case/orchestrator terpisah.
- Repository selalu return domain object/model, bukan dict mentah.
- Test unit untuk Service dengan Repository di-mock; test integration untuk Repository dengan DB nyata (PostgreSQL, mis. via container test/testcontainers).

**Potensi masalah jika struktur dibuat berbeda:**
- **Tanpa Service Layer** (Router → Repository langsung): business logic AI yang kompleks nanti akan menumpuk di router, sulit ditest, sulit dipakai ulang dari CLI/worker.
- **Tanpa Repository Pattern**: query PostgreSQL akan tersebar di banyak service, migrasi ke database lain (atau penambahan read-replica) nanti butuh ubah banyak file, bukan satu layer saja.
- **Log digabung jadi satu file**: mencari root cause error atau menganalisis performa pipeline panjang akan sangat sulit saat traffic/step bertambah banyak.
- **Config tersebar/hardcoded**: pindah environment (dev→prod) atau ganti path storage akan berisiko human error karena tersebar di banyak file.
- **`data/` & `logs/` ditaruh di dalam `app/`**: menyulitkan `.gitignore` dan migrasi ke volume terpisah saat containerisasi nanti.

---

Belum ada implementasi kode. Menunggu persetujuan struktur ini sebelum lanjut ke tahap berikutnya.
