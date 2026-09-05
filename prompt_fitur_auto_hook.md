# Prompt: Auto Hook Engine — Cold-Open Reorder + Caption Hook

Gunakan prompt ini di Claude Code (root project AutoClipper). Task terpisah dari prompt-prompt sebelumnya, tidak overlap file secara signifikan.

---

## Tujuan

Tambahkan proses "auto hook" yang jalan otomatis saat user generate clip, supaya 2-4 detik pertama klip jauh lebih menarik. Hasil akhir yang diharapkan (sudah disepakati lewat mockup storyboard):

```
0:00-0:02  Cold open — cuplikan 2 detik dari momen paling menarik di dalam window
           (yang aslinya ada di tengah/akhir), dengan efek zoom-punch + SFX whoosh.
0:02-0:04  Caption besar animasi hasil generate LLM, kalimat provokatif/penasaran
           terkait isi klip (BUKAN transkrip asli, kalimat baru).
0:04-akhir Klip asli mengalir kronologis dari awal window seperti biasa.
```

Kalau LLM gagal, momen hook tidak cukup jelas, atau window terlalu pendek — **fallback ke klip biasa tanpa hook** (behavior lama tidak berubah). Ini prinsip yang tidak boleh dilanggar: fitur ini harus 100% aman untuk gagal diam-diam, tidak boleh sampai generate clip jadi error total.

## Konteks kode yang relevan (sudah saya cek langsung)

- `app/ai_modules/llm_analysis/llm_analyzer.py` — pola LLM client yang SUDAH ADA dan jalan (httpx, OpenAI-compatible, `settings.LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`, fallback mock kalau API key kosong). **Reuse pola ini**, jangan bikin HTTP client LLM baru dari nol.
- `app/services/analysis_service.py` baris ~130 — tiap `window["segments"]` adalah list segment transcript ASLI dengan `.start_time`, `.end_time`, `.text` per kalimat (bukan cuma window-level timestamp). Ini penting — hook moment harus dicari di level segment, BUKAN minta LLM menebak angka detik (rawan meleset), tapi minta LLM pilih **index segment** dari list yang dikirim, baru kita map balik ke `segments[idx].start_time` yang presisi.
- `app/services/clip_editor_service.py::add_text()` — pola `drawtext` filter yang sudah jalan (font, escaping, warna) — reuse untuk caption overlay.
- `app/services/clip_editor_service.py::mix_sound()` — sudah ada logic mixing audio tambahan + ducking ke clip. **Reuse ini apa adanya** untuk nempel SFX whoosh, jangan bikin ulang.
- `app/services/clip_service.py::generate_clip()` — titik generate clip utama, dipanggil dari `POST /clips/generate-detail`. Ini titik integrasi Auto Hook — hook engineering dijalankan SETELAH clip biasa berhasil di-extract, sebagai tahap tambahan opsional.
- `app/models/candidate_model.py` — sudah ada kolom `hook_text` (JANGAN diubah/dipakai ulang — itu snippet transkrip mentah untuk preview list, dipakai di `preview_service.py`, `candidate_router.py`, dsb. Bikin kolom BARU untuk fitur ini supaya tidak break kontrak yang sudah ada).
- `app/models/category_model.py` — kategori belum punya kolom preferensi strategi hook.

## Yang harus dikerjakan

### 1. Migrasi database (Alembic)

Tambah kolom baru (JANGAN sentuh `hook_text` yang sudah ada):

Di `candidates`:
- `hook_moment_start: float | None` — timestamp absolut (detik, terhadap video asli) awal momen hook yang ditemukan.
- `hook_moment_end: float | None` — timestamp akhir momen hook (biasanya `hook_moment_start + 2.0`).
- `hook_type: str | None` — salah satu dari `"question" | "shock" | "stat" | "conflict" | "curiosity_gap"`.
- `hook_confidence: float | None` — 0.0-1.0 dari LLM.
- `hook_caption: str | None` — caption hasil generate LLM untuk overlay.

Di `clips`:
- `hook_applied: bool` default `False` — apakah clip ini akhirnya benar-benar dirender pakai hook (bisa saja hook moment ketemu tapi tetap gagal di render, jadi field ini beda dari sekadar "ada hook_moment_start atau tidak").
- `hook_skip_reason: str | None` — alasan kalau hook TIDAK diterapkan (untuk debug/QA): `"llm_unavailable" | "low_confidence" | "window_too_short" | "moment_too_close_to_start" | "render_failed" | None`.

Di `categories`:
- `preferred_hook_strategy: str | None` — untuk fase belajar-dari-histori nanti (fase depan, BELUM dipakai aktif di prompt ini, tapi kolomnya disiapkan sekarang supaya tidak perlu migrasi lagi nanti). Boleh selalu `None` untuk saat ini.

### 2. `HookMomentFinder` — cari momen hook via LLM

Buat file baru `app/ai_modules/hook_analysis/hook_moment_finder.py` (folder baru, ikuti pola folder analyzer lain seperti `speech_to_text/`, `llm_analysis/`).

```python
class HookMomentFinder:
    def find(self, segments: list, category_name: str | None) -> HookMoment | None:
        """
        segments: list of transcript segment object (.start_time, .end_time, .text),
                   urutan sesuai window candidate (bukan seluruh video).
        Return None kalau: segments < 4 (window kependekan buat cari momen lain),
        LLM gagal, atau confidence hasil LLM < settings.AUTO_HOOK_MIN_CONFIDENCE.
        """
```

- Reuse pola httpx client dari `llm_analyzer.py` (bikin client sendiri di kelas ini, JANGAN import instance dari `LLMAnalyzer` supaya tidak nyambung ke pipeline analisis window yang jalan untuk semua window — ini HANYA dipanggil untuk candidate yang mau di-generate, per desain hemat biaya).
- Prompt ke LLM: kirim list segment dengan format `[{"idx": 0, "text": "..."}, {"idx": 1, "text": "..."}, ...]` (index relatif ke window, BUKAN detik), minta LLM balikin JSON:
  ```json
  {"best_idx": 7, "hook_type": "shock", "confidence": 0.82, "reason": "klaim mengejutkan soal ..."}
  ```
- **Syarat tambahan penting**: `best_idx` yang dipilih HARUS berjarak minimal 3 segment ATAU minimal 5 detik dari segment pertama window (kalau momen hook-nya sudah ada di depan, tidak ada gunanya di-reorder — set `hook_skip_reason="moment_too_close_to_start"` dan return None). Validasi ini dilakukan di Python setelah dapat response LLM, jangan percaya LLM untuk aturan ini.
- Map `best_idx` ke `segments[best_idx].start_time` sebagai `hook_moment_start`, dan `min(segments[best_idx].start_time + 2.0, segments[-1].end_time)` sebagai `hook_moment_end` (jangan sampai melebihi durasi window).
- Kalau `self.api_key` kosong (LLM tidak dikonfigurasi) → langsung return `None` dengan `hook_skip_reason="llm_unavailable"`, JANGAN pakai mock random seperti di `llm_analyzer.py` — untuk fitur yang mengubah struktur video (bukan cuma skor), lebih aman diam total daripada reorder berdasarkan tebakan.

### 3. `HookCaptionGenerator` — generate teks caption

Bisa jadi method terpisah di file yang sama atau class baru `HookCaptionGenerator` di file yang sama (`hook_moment_finder.py` atau `hook_caption_generator.py`, pilih yang lebih rapi menurut agent).

- Input: teks segment hook yang terpilih + `category_name` (kalau ada, dari `candidate.category.name`) + `hook_type`.
- Prompt LLM: "buat 1 kalimat caption pendek (maks 8 kata), gaya {category_name kalau ada, default 'menarik perhatian umum'}, untuk memancing rasa penasaran terhadap momen: '{teks segment}'. Jangan ulangi kalimat aslinya, buat kalimat baru yang provokatif."
- Bisa digabung jadi SATU LLM call dengan `HookMomentFinder.find()` (irit 1 API call) — response JSON tambah field `"caption": "..."`. **Sarankan digabung** supaya total cuma 1 LLM call per candidate yang di-generate, bukan 2.
- Kalau caption kosong/gagal parse, fallback pakai potongan teks segment hook apa adanya (jangan sampai caption kosong bikin overlay teks blank).

### 4. `HookComposer` — eksekusi ffmpeg

Buat `app/services/hook_composer_service.py`, dipanggil dari `ClipService.generate_clip()` SETELAH `_extract_clip()` berhasil (klip biasa sudah ada di `output_path`).

Alur render:
1. Cek prasyarat: `settings.USE_AUTO_HOOK`, `hook_moment` tidak None, durasi window candidate minimal `settings.AUTO_HOOK_MIN_WINDOW_SECONDS` (default 20 — window kependekan bikin cold-open kerasa aneh). Kalau salah satu gagal, set `hook_skip_reason` sesuai, skip semua langkah di bawah, clip yang sudah ter-extract normal itu yang dipakai (behavior lama, tidak ada perubahan file).
2. Extract 2 detik teaser dari **video sumber asli** (`video.file_path`, BUKAN dari `output_path` yang sudah di-crop aspect ratio, supaya teaser ikut ter-crop aspect ratio yang sama nanti lewat proses yang identik dengan `_extract_clip`) — gunakan absolute timestamp `hook_moment_start` s/d `hook_moment_end`.
3. Terapkan efek zoom-punch ke teaser ini: filter ffmpeg `zoompan` sederhana dari scale 1.0 ke 1.15 dalam 0.3 detik pertama teaser, tahan di situ (bukan animasi kompleks, cukup satu step zoom yang berasa "punch"). Kalau agent menilai `zoompan` terlalu rewel untuk versi awal, alternatif lebih simpel: crop dari tengah frame ke 85% area lalu scale balik ke ukuran penuh (efek "zoomed in") tanpa animasi bertahap — sama-sama sah, pilih yang paling stabil hasilnya.
4. Terapkan caption overlay (`hook_caption`) ke teaser ini pakai POLA YANG SAMA dengan `ClipEditorService.add_text()` (drawtext, escaping karakter sama persis) — muncul dari detik 0 teaser (sesuai storyboard: 0:00-0:02 hook visual, 0:02-0:04 baru caption full muncul — TAPI supaya tidak ribet sinkronisasi, boleh sederhanakan jadi caption muncul bersamaan dari awal teaser dengan durasi 2 detik penuh, itu tetap sesuai maksud storyboard asalnya. Jangan overengineer timing kalau bikin fragile).
5. **SFX whoosh (opsional, best-effort)**: cek apakah file `data/assets/sfx/whoosh.mp3` ada. Kalau TIDAK ada, skip langkah ini saja (tidak fatal, teaser tetap jalan tanpa SFX) dan log warning sekali saja bukan tiap job. Kalau ADA, pakai `ClipEditorService.mix_sound()` yang sudah ada apa adanya untuk nempel SFX di 0.3 detik pertama teaser.
   - **Catatan untuk agent**: project TIDAK punya file SFX bawaan. Kalau developer/agent bisa cari 1 file whoosh pendek (<1 detik) royalty-free dan taruh di `data/assets/sfx/whoosh.mp3`, bagus. Kalau tidak, biarkan fitur SFX ini graceful-skip — JANGAN block seluruh fitur hook cuma karena file SFX tidak ada.
6. Concat teaser (hasil langkah 2-5) dengan clip asli utuh (`output_path` dari langkah extract normal) pakai ffmpeg **concat demuxer** (`-f concat`) — syaratnya kedua segmen harus punya codec/resolution/fps SAMA, jadi pastikan teaser di-encode dengan parameter `-c:v libx264 -crf 18 -preset fast` yang identik dengan yang dipakai `_extract_clip()`/`add_text()` supaya concat tidak gagal atau re-encode ulang saat concat (boleh re-encode saat concat kalau lebih aman, prioritaskan HASIL BENAR di atas kecepatan untuk fitur ini).
7. Hasil akhir concat menggantikan `clip.file_path` (atau simpan sebagai `clip.edited_file_path`, ikuti pola field mana yang dipakai FE untuk render — cek `_clip_result.html`/`candidate_detail_content.html` field mana yang ditampilkan, pakai itu).
8. Set `clip.hook_applied = True`. Kalau gagal di step manapun (exception), **catch, log, set `hook_skip_reason="render_failed"`, JANGAN raise** — biarkan clip hasil extract normal (langkah sebelum hook) tetap jadi hasil akhir yang dikembalikan ke user. Generate clip TIDAK BOLEH gagal total gara-gara hook error.

### 5. Setting baru

Di `app/core/config/settings.py`:
```python
USE_AUTO_HOOK: bool = True
AUTO_HOOK_MIN_CONFIDENCE: float = 0.6
AUTO_HOOK_MIN_WINDOW_SECONDS: float = 20.0
```

### 6. UI — tab baru "Hook" di halaman detail candidate

File: `app/templates/candidate_detail_content.html` (tambah 1 nav-item + 1 tab-pane, ikuti pola tab Text/Crop/Sound/Watermark yang sudah ada).

Isi tab:
- Kalau `candidate.hook_moment_start` ada: tampilkan info momen hook yang ditemukan (timestamp, `hook_type`, `hook_caption`, badge confidence), dan status apakah sudah diterapkan di clip terakhir (`clip.hook_applied` / `clip.hook_skip_reason` kalau ada).
- Kalau belum ada (candidate belum pernah di-generate, atau LLM skip): tampilkan pesan singkat "Auto hook akan dicari otomatis saat clip di-generate" — tidak perlu tombol manual trigger terpisah di fase ini (auto hook terintegrasi ke tombol Generate yang sudah ada, bukan tombol baru).
- Tambah translation key baru di `app/core/translate.py` untuk label tab dan teks-teks di atas (pola sama seperti key `candDetail.*` yang sudah ada).

### 7. Test

Tambah test baru mengikuti pola `tests/unit/test_vision_pass.py` (mock-based, tidak butuh video/API asli):
- `HookMomentFinder`: test skip kalau segments < 4, test skip kalau `best_idx` terlalu dekat ke awal, test skip kalau tidak ada API key, test parse response LLM yang valid & yang gagal parse.
- `HookComposerService`: test skip path (window pendek → `hook_skip_reason` terisi benar, clip tidak berubah), test happy path dengan ffmpeg di-mock (jangan render video sungguhan di unit test, mock `subprocess.run`).
- Test regresi: pastikan `generate_clip()` untuk candidate TANPA hook (LLM unavailable, mode test default) tetap menghasilkan clip identik dengan sebelum fitur ini ada — ini test paling penting karena membuktikan fallback aman.

## Kriteria selesai / cara verifikasi

- Set `LLM_API_KEY` valid di `.env`, generate clip dari candidate yang window-nya minimal 20 detik dan punya minimal 4 segment transcript — hasil clip harus lebih panjang ±2 detik dari durasi window asli (karena ada teaser tambahan di depan), dan 2 detik pertama secara visual berbeda dari konten yang harusnya muncul di 0:04 dst (bisa dicek manual buka file hasilnya).
- Cabut/kosongkan `LLM_API_KEY`, generate clip lagi dari candidate yang sama — hasil clip harus SAMA PERSIS seperti sebelum fitur Auto Hook ada (durasi = durasi window asli, tidak ada teaser tambahan), `clip.hook_applied=False`, `clip.hook_skip_reason="llm_unavailable"`.
- Generate clip dari candidate yang window-nya pendek (<20 detik) — harus skip hook meski LLM aktif, `hook_skip_reason="window_too_short"`.
- Tidak ada satupun kasus di mana `POST /clips/generate-detail` mengembalikan error/500 gara-gara logic hook — worst case selalu fallback ke clip biasa.
- Tab "Hook" di halaman detail menampilkan info yang benar setelah generate, dan translation key baru muncul dengan benar di UI (bukan raw key string).
