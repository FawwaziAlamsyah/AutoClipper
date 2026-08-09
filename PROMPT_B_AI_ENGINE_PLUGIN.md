# Prompt B — AI Engine Plugin-Ready (Sesuai ARCHITECTURE.md Awal)

Konteks: di `ARCHITECTURE.md` (Prompt 0) kita sepakat semua AI Module (voice, face,
gesture, scene, keyword, hook, LLM) harus jadi plugin lewat `AnalyzerInterface` +
registry, supaya model AI bisa diganti tanpa mengubah pipeline. Saat ini semua
analyzer rata di `app/services/`, dan beberapa di antaranya (`face_emotion`,
`voice_emotion`, `gesture`, `eye_contact`, `scene`, `audio`) ternyata **bukan
analisis video/audio asli** — hanya keyword/regex matching di teks transcript
(`services/validators.py`). Kerjakan Tahap A dulu sebelum tahap ini.

## Yang Harus Dikerjakan

1. **Buat struktur plugin.**
   Buat `app/ai_modules/base/analyzer_interface.py` berisi abstract class
   `AnalyzerInterface` (method minimal: `analyze(...) -> AnalysisResult`), dan
   `app/ai_modules/registry.py` untuk mendaftarkan analyzer yang aktif.

2. **Pindahkan Whisper jadi plugin.**
   Pindahkan isi `services/whisper_service.py` menjadi implementasi
   `AnalyzerInterface` di `app/ai_modules/speech_to_text/whisper_analyzer.py`.
   `TranscriptService` di layer `services/` tetap ada, tapi sekarang memanggil
   analyzer lewat registry, bukan import `whisper_service` langsung.

3. **Putuskan status analyzer yang sekarang "palsu".**
   Untuk `face_emotion`, `voice_emotion`, `gesture`, `eye_contact`, `scene`, `audio`:
   pilih salah satu per analyzer (boleh beda keputusan per jenis):
   - **(a) Jujurkan namanya** — kalau tetap mau pakai heuristik teks untuk saat
     ini, rename `analyzer_type` dari `face_emotion`/`voice_emotion`/dst menjadi
     nama yang jujur, misalnya `text_sentiment_proxy`, dan jelaskan di
     `score_breakdown` bahwa ini proxy berbasis teks, bukan analisis video/audio
     asli. Update juga label di `SCORE_WEIGHT_*` dan dokumentasi terkait.
   - **(b) Implementasikan sungguhan** — tambahkan dependency OpenCV/MediaPipe/
     DeepFace/librosa (sesuai `architecture.md` Anda) dan buat analyzer asli di
     `ai_modules/face_analysis/`, `ai_modules/voice_analysis/`, dst, yang benar-benar
     memproses file video/audio.

4. **Kalau memilih (b), kerjakan satu analyzer per giliran**, mulai dari yang
   bobotnya paling besar (`face_emotion` 8%, lalu `scene` 4%, dst), masing-masing:
   - Analyzer baru sebagai module terpisah di `ai_modules/`.
   - Didaftarkan ke `registry.py`.
   - Hasilnya tetap disimpan di tabel generik `analysis_results` (tidak perlu
     tabel baru — sesuai desain awal di `DATABASE_SCHEMA.md`).
   - **Jangan ubah `process_service.py`/pipeline orchestration** kecuali sekadar
     memanggil analyzer baru lewat registry — bukti bahwa desain plugin-ready
     kita memang bekerja.

5. **`llm_content` (kalau di Tahap A dipilih opsi disambungkan):**
   Pindahkan juga jadi plugin di `ai_modules/llm_analysis/llm_analyzer.py`,
   sesuai pola yang sama.

## Definisi Selesai

- Ada folder `app/ai_modules/` dengan minimal `base/analyzer_interface.py`,
  `registry.py`, dan `speech_to_text/whisper_analyzer.py`.
- Tidak ada lagi analyzer yang namanya menipu (mis. `face_emotion` yang isinya
  keyword matching teks) — sudah di-rename jujur atau diimplementasikan asli.
- Menambah satu analyzer baru tidak memerlukan perubahan di `process_service.py`
  selain memanggilnya lewat registry (buktikan plugin-ready-nya jalan).
- Aplikasi tetap bisa dijalankan dan test lama tetap lulus.
