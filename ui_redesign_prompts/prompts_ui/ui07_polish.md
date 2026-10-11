# UI07 — Polish: Animasi, Status Pill, Responsif, Aksesibilitas, Audit Akhir

> Prasyarat: UI01–UI06 selesai. Baca `ui00_urutan_dan_aturan.md`. Kerjakan HANYA task ini, lalu berhenti.

## Tujuan

Merapikan detail akhir agar terasa "jadi": transisi halus, indikator status di navbar, loading yang elegan, dan verifikasi menyeluruh bahwa
tidak ada fungsi yang hilang.

## File

- `app/static/css/theme-cinema.css`, `app/static/js/ui.js`
- `app/templates/base.html` (hanya untuk elemen pill di navbar)
- `app/core/translate.py` (kunci `ui.status.*`)

## Langkah

1. **Transisi halaman HTMX**: konten `#main-content` fade + naik ±8px (≤ 220ms) saat swap, memakai class bawaan HTMX
   (`htmx-added`/`htmx-settling`) atau `htmx:afterSwap` di `ui.js`. Matikan bila `prefers-reduced-motion`.
2. **Skeleton/indikator loading**: gunakan `.htmx-indicator` yang sudah ada; tambahkan gaya skeleton (shimmer abu-abu) untuk kartu saat request
   berjalan. Tidak mengubah atribut `hx-indicator` yang sudah ada.
3. **Pill status di navbar** (sisi kanan, disembunyikan di layar sempit): "Instagram · N hari" dan "TikTok". Data **dari endpoint yang sudah ada** —
   `GET /instagram/status` (field `status`, `days_left`) dan endpoint status TikTok yang sudah dipakai `checkTikTokConnection` di halaman upload (cari dan pakai yang sama).
   Warna: hijau = aktif, emas = ≤ 7 hari/peringatan, merah = perlu connect ulang, abu-abu = belum dikonfigurasi. Fetch sekali saat load dan setiap `htmx:afterSettle`
   dengan throttle (maks 1x/60 detik); gagal fetch → sembunyikan pill, jangan tampilkan error. Ini JS tampilan murni, tanpa endpoint baru.
4. **Toast & pesan**: samakan gaya semua toast/alert (kaca gelap, border tipis, ikon), tombol tutup jelas.
5. **Responsif**: uji 360, 414, 768, 1024, 1280, 1536 px. Navbar collapse rapi, grid kartu tidak terpotong saat hover, tabel lebar scroll di dalam
   wadahnya (`.table-responsive`), tidak ada scroll horizontal pada body. Perhatikan safe-area di iPhone (`env(safe-area-inset-*)`).
6. **Aksesibilitas**: kontras teks ≥ 4.5:1 (cek `--muted` dan `--faint` pada `--canvas`/`--surface`; terangkan sedikit bila perlu), `:focus-visible` pada semua
   elemen interaktif, `aria-label` untuk tombol ikon-saja, `prefers-reduced-motion` mematikan semua animasi dekoratif, urutan tab logis.
7. **Tema terang**: periksa cepat bahwa toggle ke light masih terbaca (tidak harus indah).
8. **Sapu bersih checklist detail kecil** (bagian CHECKLIST di `ui00`) di SEMUA halaman utama, bukan hanya yang disentuh task ini; laporkan temuan per halaman.
9. **Audit akhir**: `python scripts/ui_attr_audit.py check` harus lulus dengan **hanya** penghapusan yang ada di allowlist (Score Breakdown & Preview JSON).
   Jalankan juga test terkait (`tests/unit/test_ui_attr_audit.py`) dan buat daftar uji manual berikut untuk dicentang user:
   upload file, download link, polling progres job, buka detail candidate, render clip, edit clip, subtitle, kirim TikTok, kirim Instagram (dialog konfirmasi),
   like/dislike, hapus, arsip, simpan Settings, ganti bahasa/tema, Training, Storage.

## Kriteria selesai

- Audit lulus; tidak ada error JS di konsol di semua halaman utama.
- Pill status tampil benar untuk empat kondisi (uji dengan respons endpoint yang di-mock atau token dummy), dan tidak mengganggu bila endpoint gagal.
- Laporan akhir berisi: daftar semua perubahan JS (hanya string class/markup + `ui.js`), jumlah inline style sebelum/sesudah, dan checklist uji manual.

## Jangan

- Jangan menambah dependensi, endpoint, atau data baru. Jangan mengubah baseline audit.
