# AutoClipper — Analisis Full & Prompt Perbaikan

Dokumen ini berisi hasil audit source code `AutoClipper.zip` yang dikirim, plus **prompt siap-pakai** untuk 2 permintaan yang diminta. Belum ada satu pun file source yang diubah — semua perubahan didokumentasikan di sini dulu sesuai instruksi.

Cara pakai: copy bagian "PROMPT" di tiap section ke Claude Code / agent coding lain (atau ke saya di chat lain) untuk dieksekusi terhadap repo.

---

## 1. Dependency yang tidak terpakai

Saya cek satu-satu isi `requirements.txt` (22 baris) terhadap seluruh `import` di folder `app/`.

| Package | Status | Keterangan |
|---|---|---|
| fastapi | ✅ Dipakai | Core framework, 21 file |
| uvicorn | ✅ Dipakai | Entry point di `app/main.py` (`import uvicorn`) + dipakai via CLI |
| jinja2 | ✅ Dipakai (tidak langsung) | Tidak pernah `import jinja2` manual, tapi dibutuhkan oleh `fastapi.templating.Jinja2Templates` yang dipakai di 10 router. Wajib tetap ada di requirements karena FastAPI tidak bundling jinja2 secara default. |
| python-multipart | ✅ Dipakai | Dibutuhkan FastAPI untuk form/file upload |
| pydantic-settings | ✅ Dipakai | `app/core/config/settings.py` |
| alembic | ✅ Dipakai (tooling) | Tidak di-`import` di `app/`, tapi dipakai lewat `alembic/env.py` untuk migration DB — wajib tetap ada |
| sqlalchemy | ✅ Dipakai | ORM utama, 43 file |
| psycopg | ✅ Dipakai | Driver Postgres |
| pytest | ✅ Dipakai | Semua test di `tests/` |
| httpx | ✅ Dipakai | 3 file (kemungkinan util request internal / test client FastAPI) |
| yt-dlp | ✅ Dipakai | `app/services/download_service.py` |
| **curl_cffi** | ⚠️ Tidak pernah di-`import` langsung | Dipasang sebagai *impersonation backend* opsional untuk `yt-dlp` (anti-bot fingerprint). yt-dlp otomatis pakai package ini kalau terdeteksi ter-install, tapi tidak ada kode kita yang mengaktifkan/mengecek `impersonate=` secara eksplisit di `download_service.py`. **Bukan salah/dead-code, tapi manfaatnya saat ini tidak terverifikasi dipakai.** |
| **yt-dlp-ejs** | ⚠️ Tidak pernah di-`import`/referensi sama sekali, di kode maupun test | Solver n-challenge YouTube, butuh Node.js terpasang di server. Kalau server production tidak punya Node.js, package ini bisa gagal diam-diam atau jadi beban install tanpa manfaat. **Perlu konfirmasi Anda: apakah Node.js memang tersedia & fitur ini sengaja diaktifkan?** |
| faster-whisper | ✅ Dipakai | `whisper_analyzer.py` |
| nvidia-cublas-cu12 | ✅ Dipakai | Bukan di-import, tapi path DLL-nya di-load manual di `whisper_analyzer.py` (`_add_nvidia_dll_dirs`) untuk GPU Windows |
| opencv-python | ✅ Dipakai | 4 file (`cv2`) |
| mediapipe | ✅ Dipakai | 4 file, face/gesture analysis |
| librosa | ✅ Dipakai | 3 file, audio analysis |
| scikit-learn | ✅ Dipakai | `app/ml/trainer.py` |
| joblib | ✅ Dipakai | `app/ml/predictor.py`, `trainer.py` |
| **soundfile** | ⚠️ Tidak pernah di-`import` langsung di manapun (app maupun tests) | `librosa.load(...)` yang dipakai di `audio_quality_analyzer.py` & `voice_emotion_analyzer.py` sudah otomatis menarik `soundfile` sebagai dependency transitif dari librosa. Deklarasi eksplisit di `requirements.txt` ini kemungkinan besar redundant. |
| cryptography | ✅ Dipakai | `app/core/security/token_crypto.py` |

### Kesimpulan
- **Benar-benar aman dihapus (redundant):** `soundfile` — sudah otomatis ke-install lewat `librosa`, tidak ada kode yang manggil API-nya secara langsung.
- **Perlu keputusan Anda dulu (bukan dead code, tapi tidak terverifikasi kepakai secara eksplisit di kode):** `curl_cffi` dan `yt-dlp-ejs`. Ini "silent enhancer" untuk yt-dlp — kalau memang server Anda sering kena block/anti-bot YouTube atau butuh n-challenge solver, **jangan dihapus**, biarkan saja. Kalau tidak pernah masalah, boleh dihapus untuk mengecilkan image/install time.
- Semua package lain terkonfirmasi dipakai langsung di kode, **tidak direkomendasikan dihapus**.

### PROMPT (siap dipakai)

```
Di file requirements.txt AutoClipper:
1. Hapus baris `soundfile>=0.14` — sudah jadi dependency transitif dari librosa
   dan tidak ada kode yang mengimpor `soundfile` secara langsung. Verifikasi
   dengan `grep -rn "soundfile" app tests` (harus kosong) sebelum commit.
2. JANGAN hapus curl_cffi dan yt-dlp-ejs kecuali user mengonfirmasi mereka
   tidak dipakai untuk anti-bot/n-challenge YouTube — package ini dipakai
   otomatis oleh yt-dlp secara internal, bukan lewat `import` eksplisit.
3. Setelah edit, jalankan `pip install -r requirements.txt --dry-run` (atau
   equivalent) dan jalankan full test suite (`pytest`) untuk pastikan tidak
   ada regresi terkait audio loading (test_audio_quality.py, test_voice_emotion.py).
```

---

## 2. Pemisahan Candidate dari Video yang sudah di-Archive

### Temuan saat ini
Video di AutoClipper **tidak pernah di-hard-delete** — saat user "hapus" video, sistem sebenarnya hanya:
- Set `video.is_archived = True` + `archived_at`
- Hapus file fisik (source video, clip, cache) dari disk
- **Tetap simpan semua baris di DB** (candidates, transcripts, dll) — supaya data training tidak hilang

Masalahnya ada di `CandidateService.get_video_summaries()` (`app/services/candidate_service.py`) dan halaman `/candidates` (`candidates_content.html`):

```python
def get_video_summaries(self) -> list[dict]:
    videos = self.db.query(VideoModel).order_by(VideoModel.id.desc()).all()   # ⬅️ TIDAK filter is_archived
    ...
```

Query ini mengambil **semua video**, archived maupun tidak, lalu ditampilkan sebagai card yang sama persis di grid `/candidates` — tercampur berdasarkan urutan ID terbaru. Field `video.is_archived` sebenarnya sudah ada di model dan sudah dikirim ke template detail (`video_is_archived`), tapi cuma dipakai untuk menyembunyikan tombol aksi tertentu di `_candidate_row.html`, **bukan untuk memisahkan tampilan grid utama**. Persis seperti keluhan Anda: kalau sudah banyak video yang diarsipkan, grid `/candidates` akan penuh sesak / jadi spam bercampur dengan video yang masih aktif.

### Solusi yang diusulkan
Pisahkan total, sesuai pola yang sudah dipakai project ini di fitur Storage Dashboard (`/storage/dashboard` sudah punya konsep "archivable videos" terpisah):

1. **Grid utama `/candidates`** → hanya video yang `is_archived == False`.
2. **Tombol baru "📦 Lihat Arsip (N)"** di pojok kanan atas halaman `/candidates` (mirip tombol back "← Semua Video" yang sudah ada di halaman detail).
3. **Halaman baru `/candidates/archived`** → grid terpisah khusus video yang sudah diarsipkan, dengan badge "Diarsipkan" + tanggal arsip, dan tombol "← Kembali" balik ke `/candidates`.
4. Halaman detail per-video (`/candidates/video/{id}`) dan detail per-candidate **tidak perlu diubah** — itu tetap bisa diakses baik dari grid aktif maupun grid arsip, dan sudah punya guard `video_is_archived` untuk menyembunyikan aksi yang tidak relevan (misal generate ulang / render clip baru dari file yang sudah dihapus).

### PROMPT (siap dipakai)

```
Lakukan perubahan berikut di project AutoClipper untuk memisahkan candidate
dari video yang sudah di-archive, TANPA menggabungkannya ke grid candidate
yang masih aktif.

1. app/repositories/video_repository.py
   Tambahkan method baru:
     def list_archived(self) -> list[VideoModel]:
         """Video yang sudah diarsipkan, terbaru dulu."""
         return list(
             self.db.query(VideoModel)
             .filter(VideoModel.is_archived == True)  # noqa: E712
             .order_by(VideoModel.archived_at.desc())
             .all()
         )

2. app/services/candidate_service.py
   - Refactor get_video_summaries() supaya menerima parameter
     `include_archived: bool = False` dan filter query video berdasarkan
     `VideoModel.is_archived == include_archived`
     (gunakan helper privat _build_summaries(videos) untuk hindari duplikasi
     logic candidate_count/top_score/liked/disliked/clips_done yang sudah ada).
   - Tambahkan method baru:
       def get_archived_video_summaries(self) -> list[dict]:
           """Summary candidate untuk video yang SUDAH diarsipkan saja."""
           videos = self.video_repo.list_archived()
           return self._build_summaries(videos)
   - Pastikan get_video_summaries() versi default (dipanggil tanpa argumen)
     HANYA mengambil video dengan is_archived == False, supaya endpoint lama
     "/candidates" otomatis bersih dari video arsip tanpa breaking existing
     caller lain.

3. app/routers/candidate_router.py
   - Di handler `candidates_page` (GET /candidates), tambahkan hitung jumlah
     video arsip (service.video_repo.list_archived() -> len) dan kirim sebagai
     context `archived_count` ke template, supaya tombol "Lihat Arsip" bisa
     menampilkan badge angka.
   - Tambahkan route baru:
       @router.get("/archived", response_class=HTMLResponse)
       def archived_candidates_page(
           request: Request,
           service: CandidateService = Depends(get_candidate_service),
       ) -> HTMLResponse:
           """Grid candidate khusus video yang sudah diarsipkan."""
           summaries = service.get_archived_video_summaries()
           return render(
               request,
               templates,
               partial_name="candidates_archived_content.html",
               context={
                   "request": request,
                   "app_name": settings.APP_NAME,
                   "summaries": summaries,
               },
           )
     PENTING: daftarkan route "/archived" SEBELUM route dinamis apa pun yang
     bisa menabraknya (cek tidak ada konflik path di router ini — saat ini
     aman karena tidak ada path literal lain yang bentrok).

4. app/templates/candidates_content.html
   - Tambahkan tombol di header (sebelah judul, kanan atas):
       <a class="btn btn-outline-secondary btn-sm"
          href="/candidates/archived"
          hx-get="/candidates/archived"
          hx-target="#main-content"
          hx-push-url="true">
         📦 Lihat Arsip {% if archived_count %}({{ archived_count }}){% endif %}
       </a>
     Muncul terus (bukan cuma saat archived_count > 0) supaya user tetap bisa
     akses riwayat arsip meski saat ini nol.

5. Buat file BARU app/templates/candidates_archived_content.html
   - Copy struktur dari candidates_content.html (grid card video), dengan
     perubahan:
     a. Judul halaman: "Candidate Video Terarsip" + subtext penjelasan
        singkat: "Master video sudah dihapus dari storage, tapi data
        candidate & training tetap tersimpan."
     b. Tiap card dikasih badge tambahan
        `<span class="badge bg-warning text-dark">📦 Diarsipkan</span>`
        dan tanggal arsip (`s.video.archived_at`) kalau ada.
     c. Tombol "← Kembali ke Candidate Aktif" di atas, mengarah balik ke
        hx-get="/candidates".
     d. Tombol "Lihat N Candidates →" tetap sama, tetap link ke
        /candidates/video/{{ s.video.id }} (halaman detail TIDAK berubah).
     e. Empty-state kalau summaries kosong: "Belum ada video yang diarsipkan."

6. i18n (app/core/translate.py)
   Tambahkan key baru di kedua bahasa (en/id) yang dipakai di step 4 & 5,
   contoh:
     "cand.archived_title": "Archived Candidate Videos" / "Candidate Video Terarsip"
     "cand.view_archive": "View Archive" / "Lihat Arsip"
     "cand.back_to_active": "Back to Active Candidates" / "Kembali ke Candidate Aktif"
     "cand.archived_empty": "No archived videos yet." / "Belum ada video yang diarsipkan."
   Sesuaikan namespace key dengan pola existing "cand.*" yang sudah ada.

7. Test
   - Tambahkan/duplikasi test di tests/unit/test_candidate.py:
     a. get_video_summaries() TIDAK mengembalikan video dengan is_archived=True.
     b. get_archived_video_summaries() HANYA mengembalikan video dengan
        is_archived=True.
     c. Route GET /candidates/archived mengembalikan 200 dan render partial
        yang benar (candidates_archived_content.html).
   - Jalankan seluruh pytest, pastikan tidak ada regresi di
     test_routers.py / test_candidate.py yang existing.

Batasan: JANGAN ubah behaviour VideoService.delete() (archive logic) atau
model VideoModel/CandidateModel — field is_archived & archived_at sudah ada
dan cukup, tidak perlu migration/alembic baru. JANGAN gabungkan hasil
get_archived_video_summaries() ke dalam get_video_summaries() dengan flag
visual saja (mis. dim/opacity) — user secara eksplisit minta halaman/tombol
terpisah supaya grid utama tidak "spam" saat arsip menumpuk.
```

---

## Catatan tambahan (opsional, di luar 2 request Anda)

Ini bukan bagian dari permintaan Anda, sekadar saya catat kalau berguna nanti — silakan abaikan kalau tidak relevan:

- `app/routers/candidate_router.py` masih meng-import `Jinja2Templates` langsung dengan komentar `# noqa: F401 (ke AppTemplates)` di 10 file router — ini pattern konsisten di seluruh project (bukan bug), jadi tidak saya masukkan ke daftar "unused" di atas.
- `get_video_summaries()` saat ini melakukan query candidate terpisah per video di dalam loop (N+1 query pattern). Di luar scope 2 request Anda, tapi kalau jumlah video makin banyak ini bisa jadi lambat — bisa dioptimasi pakai satu query `GROUP BY` kalau nanti mau saya bantu.
