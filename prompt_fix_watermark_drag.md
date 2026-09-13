# Prompt: Fix Watermark Drag — Static Mount, Preview Foto, Boundary, Posisi Selalu Bottom

Gunakan prompt ini di Claude Code (root project AutoClipper). 4 bug terkait, di beberapa file kecil — dikerjakan sekaligus karena saling berhubungan (bug #1 kemungkinan besar akar dari bug #3).

---

## Bug 1 — Watermark tampil broken image icon, bukan logo asli

**Root cause**: folder `data/assets/` **tidak pernah di-mount** sebagai static directory. Di `app/main.py`, cuma ada:
```python
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/data/uploads", StaticFiles(directory="data/uploads"), name="uploads")
app.mount("/data/outputs", StaticFiles(directory="data/outputs"), name="outputs")
```
Tidak ada mount untuk `/data/assets`, padahal template `candidate_detail_content.html` mereferensikan `<img src="/data/assets/watermark.png?...">` — request ini selalu 404, browser render broken-image icon + alt text "watermark".

**Fix**: tambah 1 baris mount baru di `app/main.py`, sejajar dengan mount lain yang sudah ada:
```python
app.mount("/data/assets", StaticFiles(directory="data/assets"), name="assets")
```

## Bug 2 — Preview pakai `<video>` (berat), ganti jadi foto statis

Endpoint thumbnail JPEG untuk clip **sudah ada** dan sudah dipakai tab Crop: `GET /{clip_id}/thumbnail` (`app/routers/clip_router.py` baris ~178, implementasi di `FFmpegService.extract_thumbnail()`). Reuse ini, JANGAN bikin endpoint baru.

Di `candidate_detail_content.html`, ganti stage watermark (sekitar baris 322-336) dari:
```html
<div id="wm-drag-stage" class="position-relative d-inline-block mb-2" style="max-width:100%;">
  {% set raw_wm = clip.edited_file_path or clip.file_path %}
  {% set wm_preview = raw_wm.replace('\\', '/').split('data/outputs/')[-1] %}
  <video id="wm-preview-video" class="w-100 rounded" controls muted preload="metadata" style="max-height:420px;object-fit:contain;">
    <source src="/data/outputs/{{ wm_preview }}?v={{ cachebust(raw_wm) }}" type="video/mp4">
  </video>
  ...
```
menjadi (pola sama seperti tab Crop yang sudah pakai `<img>` thumbnail):
```html
<div id="wm-drag-stage" class="position-relative d-inline-block mb-2" style="max-width:100%;">
  <img id="wm-preview-img" class="w-100 rounded" style="max-height:420px;width:auto;display:block;"
       src="/clips/{{ clip.id }}/thumbnail?v={{ ts|default(0) }}" alt="preview clip">
  ...
```

**PENTING**: seluruh JS drag/resize/clamp logic yang sebelumnya baca `video.videoWidth`/`video.videoHeight`/`video.clientWidth`/`video.clientHeight` (fungsi `_wmSyncHandle`, `_wmGetEffectiveRect`, `_wmVideoRect`, event handler pointerdown/move/up, dan listener `loadedmetadata`) harus diganti sumbernya ke elemen `<img>` baru ini:
- `video.videoWidth`/`video.videoHeight` → `img.naturalWidth`/`img.naturalHeight`
- `video.clientWidth`/`video.clientHeight` → `img.clientWidth`/`img.clientHeight`
- Event `loadedmetadata` (khusus elemen `<video>`) → ganti jadi event `load` pada `<img>` (`img.addEventListener('load', ...)`), atau cek `img.complete` untuk kasus sudah ke-cache (ikuti pola yang sudah dipakai di tab Crop untuk `#crop-thumb-img`, supaya konsisten dan sudah terbukti benar).
- Ganti semua `document.getElementById('wm-preview-video')` jadi `document.getElementById('wm-preview-img')`.

Karena sumbernya sekarang foto (bukan video dengan potensi letterbox dari `object-fit:contain` + `max-height`), pertimbangkan SEDERHANAKAN `_wmVideoRect`/`_wmGetEffectiveRect` — foto yang di-render dengan `width:100%;height:auto` (tanpa `max-height` yang bisa memaksa crop) TIDAK akan ada letterbox sama sekali (gambar selalu mengisi penuh `clientWidth`/`clientHeight` elemen `<img>`-nya sendiri, beda dari kasus `<video>` sebelumnya). Kalau disederhanakan, `rect = {left: 0, top: 0, w: img.clientWidth, h: img.clientHeight}` sudah cukup, tidak perlu hitung ulang aspect-ratio letterbox lagi — TAPI kalau agent ingin tetap pakai fungsi letterbox yang sudah ada untuk jaga-jaga (misal `max-height` tetap dipertahankan di style), boleh, asal parameternya benar dibaca dari `img.naturalWidth/Height` bukan `video.videoWidth/Height`.

## Bug 3 — Kotak watermark tidak bisa di-drag sampai ke pojok

Fungsi `_wmSyncHandle()` dan mode resize di `_wmOnPointerMove()`, keduanya melakukan:
```js
img.style.width = (rect.w * _wm.scale) + 'px';
img.style.height = 'auto';   // <-- BUG
```

`img.style.height = 'auto'` itu STRING `"auto"`, bukan angka pixel. Tapi clamp vertikal di `_wmOnPointerMove()` baca:
```js
const maxTop = r.h - (parseFloat(img.style.height) || 0);
```

`parseFloat("auto")` = `NaN`. Ini bikin `maxTop` jadi `NaN`, lalu `Math.min(...)`/`Math.max(...)` dengan `NaN` selalu menghasilkan `NaN`, lalu `img.style.top = "NaNpx"` — CSS value tidak valid, browser DIAM-DIAM MENOLAK assignment ini (tidak ada height pixel yang valid buat dipakai, drag Y jadi macet total, background dari kenapa Anda merasa "kepentok" padahal ada ruang kosong).

**Fix**: jangan pakai `'auto'` untuk `img.style.height` sama sekali. Karena watermark PNG-nya biasanya punya rasio tetap, hitung height eksplisit dari rasio natural gambar:
```js
function _wmApplyWidth(img, widthPx) {
  img.style.width = widthPx + 'px';
  const ratio = (img.naturalWidth && img.naturalHeight) ? (img.naturalHeight / img.naturalWidth) : 1;
  img.style.height = (widthPx * ratio) + 'px';   // angka px eksplisit, BUKAN 'auto'
}
```
Ganti SEMUA tempat yang sebelumnya melakukan `img.style.width = ...; img.style.height = 'auto';` (ada di `_wmSyncHandle()` dan di resize-mode handler `_wmOnPointerMove()`) supaya manggil helper ini, jadi `img.style.height` SELALU berupa angka px yang valid dan bisa di-`parseFloat()` dengan benar di clamp logic.

## Bug 4 — Hasil akhir selalu nempel di bawah, tidak sesuai posisi drag

Root cause ganda (perbaiki keduanya):

**a) Konsekuensi Bug 3** — karena Y-axis drag macet (NaN), watermark secara visual TIDAK PERNAH benar-benar pindah posisi vertikal walau user drag — begitu Bug 3 di atas diperbaiki, drag Y akan berfungsi normal, dan ini kemungkinan besar sudah menyelesaikan sebagian besar masalah "selalu di bawah".

**b) Fallback diam-diam ke posisi "bottom" kalau x_pct/y_pct gagal terkirim** — di `app/services/clip_editor_service.py::add_watermark()`, kalau `x_pct`/`y_pct` yang diterima `None` (misal karena hidden input kosong/gagal ke-set), kode fallback ke:
```python
x_expr, y_expr = position_map.get(position, position_map["bottom"])
```
Dan `position` sendiri di route (`app/routers/clip_router.py`) defaultnya `Form("bottom")` — sementara dropdown `<select name="position">` yang dulu mengisi field ini **sudah dihapus** dari UI (sesuai prompt watermark draggable sebelumnya), jadi field `position` ini sekarang TIDAK PERNAH dikirim user sama sekali, selalu jatuh ke default `"bottom"`. Kombinasi ini artinya: **setiap kali x_pct/y_pct gagal terkirim sebagai angka valid — karena alasan apa pun — hasilnya selalu diam-diam jatuh ke posisi "bottom"**, persis gejala yang dilaporkan, dan tidak ada error/warning yang kelihatan ke user.

**Fix**: 
1. Pastikan `_wmSetHiddenInputs()` di frontend BENAR-BENAR jalan sebelum submit — tambahkan validasi di `submitEditForm` KHUSUS untuk form watermark: sebelum submit, cek `document.getElementById('wm-x-pct').value` dan `wm-y-pct` tidak kosong/`NaN`; kalau kosong, panggil `_wmSetHiddenInputs()` sekali lagi sebagai safety net sebelum form benar-benar di-submit (jaga-jaga kalau user klik Apply tanpa pernah drag sama sekali — pakai posisi default yang sudah ter-sync saat tab dibuka, bukan biarkan kosong).
2. Di backend (`clip_editor_service.py`), TAMBAH LOG WARNING eksplisit setiap kali jalur fallback ke `position_map` diambil PADAHAL context-nya adalah dari tab watermark drag (bukan pemanggilan lama). Karena sekarang UI watermark SELALU mengirim x_pct/y_pct (tidak ada lagi jalur dropdown position), kalau suatu saat backend menerima `x_pct=None`, itu tandanya ADA BUG di frontend — jangan biarkan silently fallback tanpa jejak:
   ```python
   if x_pct is not None and y_pct is not None:
       ...
   else:
       logger.warning(
           "add_watermark clip=%d: x_pct/y_pct kosong (None), fallback ke position=%r — "
           "ini seharusnya tidak terjadi dari UI drag, cek pengiriman form.",
           clip_id, position,
       )
       x_expr, y_expr = position_map.get(position, position_map["bottom"])
   ```

## Kriteria selesai / cara verifikasi

- Buka tab Watermark — logo watermark asli tampil (bukan broken icon), ukurannya proporsional (bukan kotak kecil default broken-image).
- Preview yang dipakai adalah foto (network tab browser harus menunjukkan request ke `/clips/{id}/thumbnail`, BUKAN file `.mp4`) — jauh lebih cepat dimuat.
- Drag watermark sampai ke pojok kanan-bawah, kiri-atas, dst — kotak watermark harus bisa mentok PERSIS di tepi frame video (bukan berhenti di tengah dengan sisa ruang kosong).
- Drag ke posisi manapun (termasuk dekat bagian ATAS frame), klik Apply — buka hasil clip-nya, watermark harus muncul di posisi yang SAMA PERSIS seperti yang terlihat di preview drag, termasuk untuk posisi non-bawah.
- Cek log server — tidak ada lagi warning "x_pct/y_pct kosong" muncul selama pemakaian normal (kalau masih muncul, berarti ada bug lain di alur pengiriman form yang perlu ditelusuri lebih lanjut dari titik itu).
