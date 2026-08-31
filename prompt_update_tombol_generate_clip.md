# Prompt: Update UI Tombol Generate Clip → Edit Video

Gunakan prompt ini di Claude Code (atau coding agent lain) di root project AutoClipper. Ini task terpisah dari prompt fix performa pipeline sebelumnya — tidak menyentuh `analysis_service.py` atau analyzer manapun.

---

## Konteks

Saat ini tombol "Generate" untuk membuat clip final muncul di **dua tempat**:
1. Di card candidate pada list/grid (`app/templates/_candidate_row.html`) — tombol `Generate` di footer card.
2. Di halaman detail candidate (`app/templates/candidate_detail_content.html`) — section "Render Clip" dengan tombol `Generate Clip (16:9 / 1080p)` (fungsi JS `doGenerateClip()`).

Saya ingin sederhanakan supaya generate clip **hanya bisa dilakukan dari halaman detail**, dengan UX yang lebih rapi.

## Perubahan yang diminta

### 1. Hilangkan tombol "Generate" dari card candidate di list/grid

File: `app/templates/_candidate_row.html`

Hapus blok tombol Generate ini (baris dengan `onclick="generateClipRow(this, {{ candidate.id }})"`):

```html
{% elif not candidate.video_is_archived %}
<button class="btn btn-sm btn-primary" onclick="generateClipRow(this, {{ candidate.id }})">{{ t("widget.generate") }}</button>
{% endif %}
```

Sisakan hanya:
- Tombol `Open` (kalau `candidate.clip_filename` sudah ada — behavior ini TIDAK berubah, tetap tampilkan link Open kalau clip sudah pernah digenerate).
- Tombol `Detail`.
- Tombol `Hapus`.

Jangan hapus/ubah bagian `{% if candidate.clip_filename %}...{% endif %}` untuk tombol Open — itu tetap perlu ada. Yang dihapus HANYA branch `{% elif %}` untuk tombol Generate.

Cek juga apakah fungsi JS `generateClipRow(...)` (kemungkinan di file JS terpisah, cari dengan `grep -rn "generateClipRow"`) masih dipakai di tempat lain. Kalau tidak dipakai lagi di mana pun setelah perubahan ini, hapus fungsi tersebut juga supaya tidak ada dead code. Endpoint backend yang dipakainya (`/clips/generate-htmx`, lihat `app/routers/clip_router.py::generate_clip_htmx`) boleh dibiarkan (tidak perlu dihapus dari router), kecuali agent yakin endpoint itu benar-benar tidak dipakai fitur lain — cukup hapus pemanggilnya dari frontend saja untuk task ini.

### 2. Rename section "Render Clip" jadi "Edit Video" di halaman detail

File: `app/core/translate.py`

Ubah value translation key `candDetail.renderClip` (saat ini di baris ~128):

```python
"candDetail.renderClip": "Render Clip",
```

menjadi:

```python
"candDetail.renderClip": "Edit Video",
```

Ini otomatis update heading `<h5>{{ t("candDetail.renderClip") }}</h5>` di `candidate_detail_content.html` tanpa perlu ubah template-nya. Cek juga apakah ada override khusus untuk locale `"id"` dengan key yang sama di file itu — kalau ada, update juga supaya konsisten (saat ini setahu saya cuma ada satu definisi di dict `"en"`, dan `"id"` fallback otomatis ke situ, tapi tolong diverifikasi ulang karena file bisa saja sudah berubah).

Konfirmasi struktur akhirnya: user harus generate clip dulu (via tombol di section ini) baru section "Edit Video" (tab Text/Crop/Sound yang sudah ada di bawahnya, key `candDetail.editClip`) bisa dipakai — flow ini SUDAH benar di kode saat ini (section edit tab hanya muncul `{% if clip %}`), jadi tidak perlu ubah struktur `{% if clip %}` yang sudah ada. Hanya title section generate-nya saja yang berubah nama.

### 3. Hilangkan teks "(16:9 / 1080p)" dari tombol generate

File: `app/templates/candidate_detail_content.html`

Ada 2 tempat teks ini muncul dan HARUS diubah bersamaan supaya konsisten (kalau cuma salah satu yang diubah, teks akan balik ke versi lama saat terjadi error):

1. Tombol awal (kondisi `{% else %}` sebelum clip ada):
   ```html
   <button class="btn btn-primary" id="generateClipBtn" onclick="doGenerateClip(this, {{ candidate.id }})">
     Generate Clip (16:9 / 1080p)
   </button>
   ```
   ubah teks jadi cukup `Generate Clip` (tanpa keterangan resolusi/aspect ratio).

2. Di dalam fungsi JS `doGenerateClip()`, pada bagian error handling (dipanggil kalau request gagal), ada 2 baris yang reset teks tombol ke `'Generate Clip (16:9 / 1080p)'` — ubah keduanya jadi `'Generate Clip'` juga, supaya konsisten dengan label awal.

Tidak perlu ubah parameter aspect_ratio yang dikirim ke backend (`aspect_ratio=16:9` di URL fetch) — itu tetap 16:9 secara default, cuma teks yang ditampilkan ke user yang disederhanakan.

### 4. Tambahkan progress bar (%) saat proses generate berjalan

Saat ini `doGenerateClip()` cuma disable tombol dan ganti teks jadi "Generating..." tanpa progress bar visual. Saya mau progress bar persentase seperti yang sudah ada di bagian lain di halaman yang sama.

**Catatan penting untuk agent**: endpoint backend `/clips/generate-detail` (`app/routers/clip_router.py::generate_clip_detail`) itu **sinkron/blocking** — proses render ffmpeg selesai dulu baru response dikirim. Jadi tidak ada data persentase real dari backend untuk endpoint ini (beda dengan job analisis di halaman upload yang punya `job_service` dengan step-based percent asli).

Implementasikan dengan cara berikut (pilih salah satu, urutan sesuai preferensi saya):

**Opsi A — cepat & konsisten dengan pola yang sudah ada di file yang sama (disarankan, low-risk):**
Di file yang sama (`candidate_detail_content.html`) sudah ada helper JS `_startEditProgress(btn)` dan `_stopEditProgress(btn)` yang dipakai untuk form edit text/crop/sound/volume — bar animasi 0%→90% berbasis waktu (bukan real backend %, tapi visualnya sudah konsisten dengan bagian lain di halaman ini). Pakai helper yang sama di `doGenerateClip()`:
```js
async function doGenerateClip(btn, candidateId) {
  _startEditProgress(btn);
  try {
    const res = await fetch(
      `/clips/generate-detail?candidate_id=${candidateId}&aspect_ratio=16:9&subtitle_enabled=false&subtitle_style=minimal`,
      { method: 'POST' }
    );
    _stopEditProgress(btn);
    if (res.ok) {
      const html = await res.text();
      document.getElementById('clip-action').outerHTML = html;
    } else {
      alert('Gagal generate clip. Coba lagi.');
    }
  } catch (e) {
    _stopEditProgress(btn);
    alert('{{ t("candDetail.error") }}');
  }
}
```
Perhatikan: `_startEditProgress`/`_stopEditProgress` saat ini mengasumsikan ada elemen `#clip-edit-preview-wrapper` sebagai tempat sisip progress bar (`wrapper.parentNode.insertBefore(div, wrapper)`). Untuk kasus generate clip pertama kali, elemen `#clip-edit-preview-wrapper` **belum ada** di DOM (baru muncul setelah clip berhasil dibuat, di blok `{% if clip %}`). Jadi buat variasi helper baru khusus, misalnya `_startGenerateProgress(btn)` / `_stopGenerateProgress(btn)`, yang menyisipkan progress bar tepat di dalam `#clip-action` (sebelum/sesudah tombol), dengan pola animasi & styling yang sama persis (copy logic-nya, ubah target elemennya saja).

**Opsi B — progress % asli dari backend (lebih akurat, effort lebih besar):**
- Ubah `generate_clip_detail` supaya jalan di background thread (`threading.Thread`), lalu simpan progress state (bisa in-memory dict per `candidate_id`, atau tabel baru) yang di-update dengan mem-parsing output `-progress pipe:1` dari proses ffmpeg (ffmpeg bisa keluarkan `out_time_ms` secara berkala ke stdout kalau dipanggil dengan flag itu). Karena durasi clip target sudah diketahui (`candidate.end_time - candidate.start_time`), persentase = `out_time_ms / (durasi_target * 1000) * 100`.
- Tambah endpoint baru, misalnya `GET /clips/generate-detail/status/{candidate_id}`, yang return `{ "percent": ..., "status": "running|completed|failed" }`.
- Endpoint `POST /clips/generate-detail` diubah supaya langsung return response cepat (mis. status "started") setelah men-trigger thread, TIDAK menunggu ffmpeg selesai.
- Di frontend, ganti `doGenerateClip()` supaya setelah trigger start, polling endpoint status setiap 1-2 detik (pola sama seperti `hx-trigger="load, every 2s"` di `job_detail_content.html`, atau pakai `setInterval` + `fetch` manual seperti fungsi `pollTikTokStatus()` yang sudah ada di file yang sama — reuse pola itu paling gampang karena sudah ada contohnya persis di file ini), update progress bar, dan render `_clip_result.html` setelah `status === "completed"`.

Silakan agent pilih Opsi A dulu untuk quick win (bisa selesai cepat, resiko rendah, tidak ubah backend sama sekali). Kalau saya minta progress akurat nanti, baru lanjut ke Opsi B sebagai iterasi berikutnya — TIDAK perlu dikerjakan sekarang kecuali saya minta eksplisit.

## Kriteria selesai / cara verifikasi

- Buka halaman list candidate per video: pastikan card TIDAK ADA lagi tombol Generate, hanya Open (kalau clip sudah ada)/Detail/Hapus.
- Buka halaman detail salah satu candidate yang belum punya clip: pastikan section generate sekarang berjudul **"Edit Video"**, tombolnya bertuliskan **"Generate Clip"** saja (tanpa `(16:9 / 1080p)`).
- Klik tombol generate: pastikan progress bar animasi muncul (persentase berjalan), lalu berganti ke tampilan "Clip sudah dibuat" (`_clip_result.html`) setelah selesai, sama seperti alur lama tapi dengan tambahan progress bar.
- Pastikan tidak ada bagian lain di app (misalnya halaman `candidates_video_content.html` atau `candidates_content.html` yang me-render `_candidate_row.html`) yang jadi rusak/error karena hilangnya tombol Generate di card.
- Jalankan test yang ada terkait candidate row / clip generation kalau ada (`grep -rln "generateClipRow\|_candidate_row" tests/`), update kalau perlu.
