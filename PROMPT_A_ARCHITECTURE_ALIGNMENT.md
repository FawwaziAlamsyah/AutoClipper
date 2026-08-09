# Prompt A — Architecture Alignment (Rapikan Pelanggaran, Tanpa Fitur Baru)

Konteks: project AI Auto Clipper sudah berjalan (upload, download, extract, transcribe,
analisis, candidate, render clip, subtitle, history, dashboard), tapi ada beberapa
penyimpangan dari arsitektur yang sudah disepakati di awal (lihat `00_GAP_ANALYSIS.md`).
Tahap ini HANYA merapikan pelanggaran arsitektur — jangan tambah fitur baru dulu.

## Yang Harus Dikerjakan

1. **Router tidak boleh menyentuh DB langsung.**
   Pindahkan semua query DB langsung di `app/main.py` (fungsi `index()`) dan
   `app/routers/video_router.py` (fungsi `upload_page()`) ke Service yang sesuai
   (mis. `DashboardService` baru untuk statistik dashboard, atau method baru di
   `JobService` untuk daftar job yang sedang berjalan). Setelah ini, tidak boleh
   ada lagi `db.query(...)` atau import model langsung di layer `routers/`.

2. **Satukan semua provider Service ke satu DI container.**
   Konsolidasikan seluruh provider (`_get_service()` yang sekarang tersebar di
   `video_router.py`, `job_router.py`, `preview_router.py`, dst) ke dalam
   `app/core/di/dependencies.py`. Setiap router tinggal `Depends(get_xxx_service)`
   dari sana, tidak mendefinisikan provider sendiri lagi.

3. **Samakan penamaan class model dengan coding convention.**
   Rename class ORM dari `Video`, `Job`, `Clip`, `Candidate`, dst menjadi
   `VideoModel`, `JobModel`, `ClipModel`, `CandidateModel`, dst — sesuai konvensi
   di `PROJECT_FOUNDATION.md`. **Nama tabel di database TIDAK berubah**, ini murni
   rename class Python + semua import yang mereferensikannya. Kalau ada perubahan
   struktur DB yang ikut terdampak, generate migrasi Alembic baru; kalau tidak ada
   perubahan kolom/tabel, tidak perlu migrasi baru.

4. **Hilangkan duplikasi Score Engine.**
   Saat ini `score_engine.py` (dipakai `candidate_service.py`) dan
   `analysis_service._merge_scores()` sama-sama menghitung `final_score` secara
   independen. Pilih satu sebagai satu-satunya sumber kebenaran (rekomendasi:
   pertahankan `score_engine.py` karena sudah dipisah rapi sebagai service
   tersendiri), lalu hapus logika penghitungan skor yang terduplikasi di
   `analysis_service.py` — biarkan `analysis_service` hanya menghasilkan
   raw analyzer scores, dan `score_engine.py` yang menggabungkannya jadi
   `final_score` + `score_breakdown`.

5. **Putuskan nasib `llm_service.py`.**
   File ini ada tapi tidak pernah dipanggil dari mana pun (dead code), padahal
   `SCORE_WEIGHT_LLM_CONTENT` adalah bobot terbesar (30%) di score engine.
   Pilih salah satu:
   - **(a)** Sambungkan sungguhan: panggil `llm_service.py` dari `analysis_service.py`
     untuk menghasilkan analyzer_type `"llm_content"` yang nyata, atau
   - **(b)** Kalau belum mau diimplementasikan sekarang, hapus dulu file dan
     bobot terkait supaya tidak ada kode/skor yang menipu (pura-pura ada LLM
     padahal tidak).

## Yang Tidak Boleh Dilakukan di Tahap Ini

- Jangan bikin analyzer AI baru (itu Tahap B).
- Jangan ubah UI/template (itu Tahap D).
- Jangan ubah daftar `job_steps` yang tercatat (itu Tahap C).

## Definisi Selesai

- Tidak ada lagi `db.query()`/import model di `routers/` maupun `main.py`.
- Semua router memakai provider dari `core/di/dependencies.py`.
- Semua class model berakhiran `Model`.
- Hanya ada satu tempat yang menghitung `final_score` candidate.
- `llm_service.py` sudah jelas statusnya: terpakai nyata, atau dihapus.
- Aplikasi tetap bisa dijalankan (`uvicorn app.main:app --reload`) dan semua test lama tetap lulus.
