# Prompt C — Progress Tracker Sesuai Additional_1.md

Konteks: `Additional_1.md` meminta Progress Tracker realtime dengan ~20 step
(Upload, Download, Extract Audio, Extract Frames, Speech To Text, Transcript
Segmentation, Face Detection, Face Emotion Analysis, Voice Analysis, Speaker
Detection, Keyword Analysis, Hook Detection, Story Detection, LLM Analysis,
Score Engine, Candidate Clip Generation, Subtitle Generation, Preview Generation,
Final Render, Finished), masing-masing dengan status/persentase/waktu
mulai-selesai-durasi. Saat ini `job_steps` yang benar-benar tercatat di backend
cuma `extract → transcribe → analyze`. Kerjakan Tahap A & B dulu sebelum tahap ini,
supaya daftar step yang dicatat mencerminkan analyzer yang benar-benar ada.

## Yang Harus Dikerjakan

1. **Definisikan daftar step final** berdasarkan analyzer yang benar-benar
   berjalan setelah Tahap B selesai (bukan daftar aspirational dari
   `Additional_1.md` yang lama). Kalau sebagian analyzer di Tahap B masih
   opsi (a) — heuristik teks yang di-rename jujur — step-nya tetap boleh
   dicatat, tapi labelnya harus sesuai nama jujur tadi.

2. **Perluas pencatatan `job_steps`** di `JobService`/`process_service.py` agar
   mencatat setiap step nyata di atas (bukan cuma 3 step lama), termasuk
   `score`, `generate` (render clip), `export`, dan step-step analyzer baru dari
   Tahap B — masing-masing dengan `started_at`, `finished_at`, `duration_ms`,
   sesuai kolom yang sudah ada di tabel `job_steps`.

3. **Sediakan endpoint status yang mengembalikan semua step tersebut**
   (perluas `GET /jobs/{job_id}` yang sudah ada di `job_router.py`) berikut
   persentase progres keseluruhan (jumlah step selesai / total step).

4. **Update tampilan progress** (lihat juga Prompt D untuk sisi UI) supaya
   daftar step yang ditampilkan ke user match persis dengan yang tercatat di
   backend — jangan menampilkan step yang tidak benar-benar berjalan.

## Definisi Selesai

- `job_steps` mencatat seluruh tahap nyata dari upload sampai finished, bukan
  cuma 3 tahap lama.
- `GET /jobs/{job_id}` mengembalikan seluruh step beserta status/waktu/durasi.
- Tidak ada step yang ditampilkan di response API tapi sebenarnya tidak pernah
  dijalankan backend.
- Aplikasi tetap bisa dijalankan dan test lama tetap lulus.
