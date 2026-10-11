# UI05b — Detail Klip: Panel Render, Edit, Subtitle, TikTok, Instagram

> Prasyarat: UI05a selesai. Baca `ui00_urutan_dan_aturan.md`. Kerjakan HANYA task ini, lalu berhenti.

## Tujuan

Restyle isi panel di halaman detail agar rapi dan konsisten dengan tema, tanpa mengubah satu pun fungsi.
Ini file paling berisiko: kerjakan **per panel**, jalankan audit setelah tiap panel.

## File

- `app/templates/candidate_detail_content.html`
- `app/templates/_clip_edit_preview.html`, `_clip_result.html`, `_subtitle_form.html`, `_subtitle_result.html`, `_rating_control.html`
- `app/static/css/theme-cinema.css` (bagian `/* detail panels */`)
- `app/core/translate.py` (kunci baru `ui.detail.*` bila perlu)

## Langkah (urut per panel)

1. **Render Clip**: judul panel + deskripsi pendek; kontrol (pilihan rasio, durasi, opsi hook, dll.) ditata dalam grid dua kolom dengan label kecil abu-abu;
   field memakai gaya gelap; tombol utama "Generate/Render" = merah penuh lebar panel; status/hasil render (`_clip_result.html`) tampil sebagai kartu hasil
   dengan chip hijau/merah. Semua nama field, id, dan handler tetap.
2. **Blok kirim TikTok**: tombol putih (teks hitam) bergaya platform, badge status "TikTok ✓" bila sudah terkirim, area progres memakai progress merah.
3. **Blok kirim Instagram** (dari task Instagram): textarea caption gelap + penghitung karakter/hashtag (merah bila melewati batas), segmented control
   `igFitMode` (pad/blur/off) bergaya pill seperti preview, tombol gradien Instagram, catatan kecil abu-abu, dan area status/progres `instagram-publish-status`.
   Bila elemen-elemen itu belum ada di repo (Task 05/06 Instagram belum diterapkan), lewati bagian ini dan laporkan.
4. **Edit Clip** (kartu besar ±350 baris, memuat `_clip_edit_preview.html` dan JS timeline/slider): kelompokkan kontrol dalam sub-seksi
   berjudul kecil (`.section-label`); slider/range, input waktu, dan tombol pratinjau memakai gaya tema (track abu-abu, thumb/isi merah);
   area preview video di kiri dengan latar hitam dan radius. **Jangan** mengubah id/elemen yang dipakai JS timeline.
5. **Subtitle**: form (`_subtitle_form.html`) dengan select/field gelap, pratinjau hasil (`_subtitle_result.html`) dalam kartu; tombol utama merah.
6. **Inline style**: ke-33 `style=""` di file ini — ubah yang **statis** menjadi class di CSS; yang berisi nilai dinamis (`{{ … }}`) atau yang dimanipulasi JS
   (`element.style.display`) biarkan. Catat jumlah sebelum/sesudah di laporan.
7. **JS yang membuat markup** (progres TikTok/Instagram/subtitle, pesan error): sesuaikan hanya string class (mis. `alert alert-danger` → class tema, `progress-bar` tetap
   bila Bootstrap progress dipakai). Laporkan tiap baris JS yang disentuh.

## Kriteria selesai

- `python scripts/ui_attr_audit.py check` lulus; peringatan `<script>` hanya untuk string class/markup dan masing-masing dijelaskan.
- Uji manual (dilaporkan, tanpa mem-publish ke akun asli): render klip, edit/pratinjau, generate subtitle, tombol kirim TikTok dan Instagram menampilkan
  validasi/dialog seperti sebelumnya, penghitung caption bekerja.
- Tidak ada elemen yang overflow horizontal di 360px; panel kanan tetap sticky di desktop dan scroll internal bila lebih tinggi dari viewport (`max-height` + `overflow:auto`).

## Jangan

- Jangan mengubah urutan field form, nama field, endpoint, atau logika JS. Jangan memecah/menyatukan panel.
