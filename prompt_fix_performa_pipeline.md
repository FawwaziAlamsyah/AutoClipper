# Prompt: Fix Bottleneck Performa Pipeline Analisis Video (AutoClipper)

Gunakan prompt ini di Claude Code (atau coding agent lain) di dalam root project AutoClipper.

---

## Konteks

Pipeline processing video (`app/services/process_service.py` → `app/services/analysis_service.py`) berjalan **sangat lambat** untuk video panjang (contoh: video 83 menit butuh >1 jam hanya di tahap `analyze`). Saya sudah trace root cause-nya lewat log dan source code. Tolong lakukan perbaikan berikut, urut dari dampak terbesar.

## Root cause yang sudah dikonfirmasi

1. **Bottleneck utama**: 4 analyzer visual — `app/ai_modules/face_analysis/face_emotion_analyzer.py`, `app/ai_modules/gesture_analysis/gesture_analyzer.py`, `app/ai_modules/face_analysis/eye_contact_analyzer.py`, `app/ai_modules/scene_analysis/scene_change_analyzer.py` — masing-masing memanggil `cv2.VideoCapture(video_path)` **dari nol lalu `cap.set(cv2.CAP_PROP_POS_MSEC, ...)` di SETIAP window** (sampai 150 window per job, lihat `MAX_WINDOWS_PER_JOB` di `analysis_service.py`). Total ini bisa jadi 4 × 150 = 600 kali buka+seek video mentah 1080p60, murni sekuensial (dipanggil satu per satu di `AnalysisService._run_plugin_analyzers`). Seek dengan `CAP_PROP_POS_MSEC` di H.264 mahal karena decoder harus mundur ke keyframe terdekat lalu decode maju.
2. **Tidak ada paralelisme sama sekali** di `process_service.py` maupun `_run_plugin_analyzers` — semua analyzer dan semua window diproses sinkron satu-satu di main thread/process.
3. **Log spam MediaPipe (`Failed to send to clearcut: FAILED_PRECONDITION`)** adalah telemetry internal MediaPipe, bukan bug pipeline, tapi berpotensi menambah I/O/network delay tiap ±60 detik. Fix env var `MEDIAPIPE_DISABLE_TELEMETRY` sudah ada di `app/ai_modules/speech_to_text/whisper_analyzer.py::_load_model`, tapi **tidak efektif** karena `mediapipe` sudah ter-import lebih dulu lewat modul lain (`gesture_analyzer.py`, `face_emotion_analyzer.py`, `eye_contact_analyzer.py` meng-import `mediapipe` di level modul, dan modul-modul ini kemungkinan besar sudah dimuat saat registry di-import di startup, sebelum whisper analyzer sempat jalan).
4. **Whisper model check** memicu HTTP request ke `huggingface.co/api/models/...` setiap job dijalankan (terlihat di log), menambah dependensi jaringan yang tidak perlu kalau model sudah ter-cache lokal.

## Yang harus dikerjakan

### 1. Refactor 4 analyzer visual jadi satu single-pass decode per video per job

Tujuan: video hanya dibuka & di-decode **sekali secara sekuensial** (bukan seek random per window), lalu hasil deteksi (face landmarks, hand landmarks, frame diff untuk scene) dibagikan ke semua window yang relevan.

Implementasi yang disarankan:
- Buat satu class/service baru, misalnya `VideoVisionPass` di `app/ai_modules/` (atau di `analysis_service.py` langsung), yang:
  - Membuka `cv2.VideoCapture(video_path)` **satu kali**.
  - Melakukan iterasi frame secara berurutan dari awal sampai akhir video (atau dari `min(window.start)` sampai `max(window.end)` kalau ada `analyze_start_time`/`analyze_end_time`), TANPA seek ulang — cukup `cap.read()` berurutan.
  - Untuk setiap frame yang dibaca, cek timestamp-nya masuk ke window mana saja (window overlap, jadi satu frame bisa relevan untuk >1 window — gunakan interval lookup, bisa pakai sorted list + pointer window aktif berjalan maju seiring waktu video berjalan, bukan re-scan semua window tiap frame).
  - Jalankan `FaceLandmarker.detect()` dan `HandLandmarker.detect()` HANYA SEKALI per frame (bukan sekali per analyzer per frame) — cache hasil deteksi per frame, lalu pakai hasil yang sama untuk hitung skor `face_emotion`, `eye_contact`, dan `gesture` (karena `face_emotion` dan `eye_contact` sama-sama pakai `FaceLandmarker` dengan landmark index berbeda — jangan load model dua kali, cukup satu instance `FaceLandmarker` untuk keduanya).
  - Untuk `scene_change_analyzer`, hitung frame-diff terhadap frame sebelumnya secara langsung dalam loop yang sama (tidak perlu decoder terpisah).
  - Batasi jumlah frame yang diproses per window tetap sesuai `_MAX_FRAMES` yang sudah ada di masing-masing analyzer lama, tapi terapkan sebagai sampling rate (misal ambil 1 dari setiap N frame) alih-alih membaca N frame pertama window secara mentah — supaya representatif untuk window yang durasinya lebih panjang dari cakupan `_MAX_FRAMES`.
  - Setelah loop selesai, agregasi hasil per window dan simpan ke `AnalysisResultModel` seperti pola yang sudah ada sekarang di `AnalysisService._run_plugin_analyzers` (JANGAN ubah skema DB atau kontrak `AnalyzerInterface.analyze()` untuk analyzer lain yang tidak terkait video, seperti `llm_content`, `voice_emotion`, `audio` — biarkan tetap pakai jalur lama).
- Pastikan `job_service.start_step`/`finish_step` tetap dipanggil untuk tiap `analyzer_type` (`face_emotion`, `gesture`, `eye_contact`, `scene`) supaya progress bar UI di halaman upload tidak berubah kontraknya — hanya proses internalnya yang digabung.
- Tulis/update unit test yang relevan (`tests/unit/test_gesture.py`, `test_face_emotion_analyzer.py`, `test_eye_contact.py`, `test_scene.py`) supaya tetap lulus dengan interface baru, dan tambahkan test baru untuk pastikan single-pass decode menghasilkan skor yang setara (dalam toleransi wajar) dengan versi lama untuk sample video pendek.

### 2. Downscale video untuk analisis visual (proxy video)

- Sebelum single-pass decode di atas dijalankan, buat step baru (bisa di `ffmpeg_service.py`) untuk generate **proxy video beresolusi rendah** khusus untuk kebutuhan deteksi wajah/tangan/scene — bukan untuk output final clip (output final clip tetap pakai `video.file_path` asli, jangan diubah).
- **Default konservatif**: scale ke **height 480px, FPS TETAP sama dengan sumber (jangan diturunkan)**. Turunkan resolusi dulu saja di tahap ini — jangan sentuh fps sama sekali, supaya sampling temporal (gesture cepat, scene cut singkat) tidak ikut terdampak sebelum ada data pembanding yang cukup.
- Buat nilai resolusi ini **configurable** (env var atau setting, bukan hardcode) supaya gampang disesuaikan naik/turun setelah lihat hasil validasi di poin berikut.
- Simpan proxy ini di cache (pola serupa dengan cache audio yang sudah ada, key seperti `video:{video_id}:vision_proxy`) supaya tidak digenerate ulang kalau job dijalankan lagi untuk video yang sama.
- `VideoVisionPass` di atas membaca dari proxy ini, bukan dari video asli 1080p60.
- Pastikan mapping timestamp start/end window tetap benar terhadap proxy (karena hanya resolusi yang diturunkan, bukan fps/durasi, seharusnya timestamp tetap valid — tapi tolong verifikasi dengan test).

**Validasi wajib sebelum rollout — A/B score comparison:**
- Ambil minimal 2-3 video sample yang representatif (durasi bervariasi, termasuk yang punya wajah/gesture jelas dan yang lebih statis).
- Jalankan pipeline analisis **dua kali** untuk video yang sama: sekali pakai video asli (jalur lama, sebelum ada proxy), sekali pakai proxy 480p.
- Bandingkan `score_breakdown` per window untuk `face_emotion`, `gesture`, `eye_contact`, `scene` di antara kedua run — catat delta skor per analyzer (bukan cuma `final_score` gabungan, karena penting lihat drift per-analyzer, bukan cuma hasil akhir yang kebetulan mirip karena saling menutupi).
- Catat juga apakah urutan ranking candidate (mana yang jadi top-20 klip) berubah signifikan antara run lama vs run dengan proxy — ini indikator paling penting karena langsung memengaruhi klip mana yang akhirnya dipilih user.
- Tulis hasil perbandingan ini (bisa markdown singkat atau print ke log) supaya bisa direview sebelum diputuskan proxy 480p ini di-enable permanen untuk semua job atau perlu naik ke resolusi lebih tinggi (mis. 720p) kalau ternyata drift skornya terlalu besar.
- Jangan hapus jalur lama (analisis pakai video asli) dari kode — cukup buat toggle/flag supaya bisa dibandingkan lagi kapan saja kalau nanti perlu tuning ulang.

### 3. Fix urutan import supaya `MEDIAPIPE_DISABLE_TELEMETRY` benar-benar berlaku

- Pindahkan environment variable berikut ke baris **paling atas** entrypoint aplikasi (file `main.py` atau `app/main.py`, sebelum import lain apa pun termasuk `app.ai_modules.registry`):
  ```python
  import os
  os.environ.setdefault("MEDIAPIPE_DISABLE_TELEMETRY", "1")
  os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
  os.environ.setdefault("GLOG_minloglevel", "3")
  ```
- Hapus/boleh biarkan duplikat di `whisper_analyzer.py` (tidak berbahaya, tapi sudah tidak perlu jadi satu-satunya tempat).
- Verifikasi dengan menjalankan satu job test dan pastikan log `Failed to send to clearcut` tidak muncul lagi.

### 4. Hindari network check huggingface tiap job

- Di `whisper_analyzer.py`, saat load `WhisperModel`, tambahkan env var `HF_HUB_OFFLINE=1` (atau parameter `local_files_only=True` kalau didukung versi `faster-whisper`/`huggingface_hub` yang dipakai) SETELAH memastikan model sudah pernah di-download minimal sekali sebelumnya. Kalau model belum ada, biarkan mode online dulu (fallback), baru set offline setelah `WhisperModel` berhasil dibuat sekali — atau cukup deteksi apakah file model sudah ada di local cache dir sebelum decide mode online/offline.
- Tujuannya supaya job kedua dan seterusnya tidak menunggu round-trip network ke huggingface.co.

### 5. (Opsional, kalau waktu masih memungkinkan) Paralelkan antar analyzer independen

- Analyzer yang tidak saling bergantung (`llm_content`, `voice_emotion`, `audio` vs kelompok visual yang sudah digabung di poin 1) bisa dijalankan **concurrent** menggunakan `concurrent.futures.ProcessPoolExecutor` atau `ThreadPoolExecutor` tergantung sifat kerjanya (CPU-bound murni → proses terpisah lebih efektif karena GIL).
- Kalau ini dianggap terlalu berisiko untuk sekali jalan, boleh di-skip dulu — prioritaskan poin 1–4 karena itu yang paling menjelaskan angka di log (face_emotion butuh ~19.5 menit sendirian untuk 150 window).

## Kriteria selesai / cara verifikasi

- Jalankan ulang satu job dengan video test yang representatif (durasi minimal 20–30 menit) dan bandingkan:
  - Waktu total tahap `analyze` sebelum vs sesudah perubahan (harus turun signifikan, target minimal 3-4x lebih cepat untuk kelompok analyzer visual).
  - Skor akhir kandidat (`final_score`, `score_breakdown`) tidak berubah drastis dibanding hasil lama (toleransi wajar, karena sampling frame boleh sedikit berbeda).
  - Log tidak lagi berisi baris `Failed to send to clearcut` berulang.
  - Log tidak lagi menunjukkan `cv2.VideoCapture` dipanggil ratusan kali (bisa ditambahkan log debug sementara untuk menghitung jumlah `VideoCapture` yang dibuka per job, lalu hapus setelah verifikasi).
- Pastikan semua test di `tests/unit/` yang menyentuh analyzer visual tetap lulus, dan tambahkan test baru sesuai kebutuhan.
- Jangan ubah kontrak API/response yang dipakai frontend (`upload_content.html`, endpoint job progress) — progress bar dan step name harus tetap sama persis dari sisi user.

Tolong kerjakan bertahap: mulai dari poin 3 dan 4 (perubahan kecil, low-risk, cepat), lalu poin 1 (perubahan besar, high-impact), baru poin 2, dan poin 5 di akhir kalau masih ada waktu. Setelah tiap poin selesai, jalankan test suite yang relevan sebelum lanjut ke poin berikutnya.
