```
Perbaiki halaman detail candidate di AutoClipper: setelah user klik tombol
"Generate Clip" dan proses generate selesai, preview clip + menu edit
(tab Text/Crop/Sound/Watermark) + tombol upload TikTok TIDAK langsung
muncul — user harus reload browser manual dulu. Perbaiki supaya semuanya
otomatis muncul tanpa reload manual, pakai JS saja, dengan cara paling
sederhana yang SUDAH jadi pola konsisten di project ini (lihat
job_detail_content.html: fungsi cancelJob() dan
training_dashboard_content.html yang sudah pakai pola serupa) — JANGAN
bikin pola baru yang berbeda.

Root cause: doGenerateClip() di app/templates/candidate_detail_content.html
saat ini cuma me-replace elemen #clip-action dengan hasil render
_clip_result.html (POST /clips/generate-detail), yang isinya HANYA pesan
"Clip sudah dibuat" + form generate subtitle. Padahal blok-blok berikut di
candidate_detail_content.html dibungkus kondisi Jinja `{% if clip %}` dan
CUMA di-render saat request awal ke server (GET /candidates/{candidate_id}):
- Tombol/status upload TikTok (`tiktokPublishBtn` dkk)
- Card "Edit Clip" berisi `#clip-edit-preview-wrapper` (preview video hasil
  generate) + tab Text/Crop/Sound/Watermark
Karena _clip_result.html tidak mengandung blok-blok itu, mereka baru
muncul kalau halaman di-reload (server re-render ulang dengan variabel
`clip` yang sekarang sudah terisi).

Perbaikan (JS-only, tanpa endpoint/backend baru):
1. app/templates/candidate_detail_content.html — function doGenerateClip():
   - Setelah `res.ok` dan animasi progress bar diselesaikan (bagian yang
     sudah ada, set width 100% dsb — PERTAHANKAN bagian ini, jangan
     dihapus, supaya user tetap lihat feedback progress selesai), GANTI
     baris `document.getElementById('clip-action').outerHTML = html;`
     dengan pola refresh-in-place yang sudah dipakai di
     job_detail_content.html (fungsi cancelJob()):
       const pageRes = await fetch(window.location.pathname, {
         headers: { 'HX-Request': 'true' }
       });
       if (pageRes.ok) {
         document.getElementById('main-content').innerHTML = await pageRes.text();
       } else {
         // fallback: tetap tampilkan hasil parsial minimal supaya user
         // tidak stuck tanpa feedback sama sekali
         document.getElementById('clip-action').outerHTML = html;
       }
     Catatan: `window.location.pathname` saat berada di halaman detail
     candidate ini SUDAH berupa `/candidates/{candidate_id}` (via
     hx-push-url yang sudah ada di navigasi existing), jadi tidak perlu
     hardcode candidateId ke path — cukup pastikan behavior ini benar
     dengan mengecek route GET /candidates/{candidate_id} di
     app/routers/candidate_router.py (function candidate_detail).
   - Setelah innerHTML #main-content diganti, seluruh halaman detail
     ter-render ulang dari server dengan variabel `clip` yang sudah terisi
     → otomatis memunculkan preview clip, tab edit, dan tombol TikTok
     tanpa perlu reload manual maupun endpoint tambahan.
   - Setelah swap innerHTML, tambahkan `window.scrollTo` atau
     `element.scrollIntoView({ behavior: 'smooth', block: 'start' })` ke
     card "Generate Clip" / "Edit Clip" yang baru muncul (cari by heading
     text atau tambahkan id anchor baru kalau belum ada), supaya user
     tidak bingung posisi scroll balik ke atas setelah full innerHTML
     diganti.
   - Bungkus fetch tambahan ini dalam try/catch yang sama seperti kode
     existing — kalau fetch kedua ini gagal (network error dsb), fallback
     ke behavior lama (`document.getElementById('clip-action').outerHTML
     = html;`) supaya user tetap dapat feedback minimal, tidak stuck di
     progress bar.

2. TIDAK perlu ubah apa pun di:
   - app/routers/clip_router.py (endpoint /clips/generate-detail tetap
     sama, responsnya _clip_result.html masih dipakai sebagai fallback)
   - app/routers/candidate_router.py (endpoint GET /{candidate_id} yang
     dipakai untuk refresh sudah lengkap dan benar, tidak perlu endpoint
     baru)
   - Tidak perlu tabel/migration DB, tidak perlu polling interval, tidak
     perlu WebSocket — progress bar visual yang sudah ada tetap dipakai
     sebagai animasi selama proses generate berjalan (unchanged), hanya
     langkah SETELAH sukses yang diperbaiki.

3. Test manual yang perlu diverifikasi setelah perubahan:
   - Klik "Generate Clip" di candidate yang belum punya clip → setelah
     progress bar selesai, TANPA reload: preview video, tab edit
     (Text/Crop/Sound/Watermark), dan tombol upload TikTok harus langsung
     terlihat.
   - Scroll position setelah auto-refresh tidak melompat ke posisi aneh
     (paling atas halaman atau posisi acak) — harus tetap masuk akal bagi
     user (idealnya tetap di sekitar area Generate Clip / Edit Clip).
   - Kalau fetch refresh gagal (simulasikan offline/network error), user
     tetap melihat pesan "Clip sudah dibuat" (fallback lama), bukan layar
     kosong atau error tanpa feedback.
   - Ulangi generate untuk beberapa candidate berbeda untuk pastikan tidak
     ada regresi di alur lain (misalnya tombol subtitle, tombol reset edit)
     yang bergantung pada elemen dengan id tertentu di dalam
     #main-content — pastikan semua id (clip-edit-preview-wrapper,
     tiktokPublishBtn, dst.) tetap unik dan berfungsi setelah innerHTML
     di-replace.
```
