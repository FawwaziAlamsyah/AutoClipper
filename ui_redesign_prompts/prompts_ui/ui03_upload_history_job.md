# UI03 — Upload, History, Job Detail

> Prasyarat: UI01–UI02 selesai. Baca `ui00_urutan_dan_aturan.md`. Kerjakan HANYA task ini, lalu berhenti.

## Tujuan

Halaman upload/download yang terasa modern (drop-zone, langkah jelas), riwayat yang rapi, dan detail job berupa stepper vertikal.
Semua form, input file, tombol, dan skrip upload/polling tetap berfungsi persis seperti sekarang.

## File

- `app/templates/upload.html` **dan** `app/templates/upload_content.html` (ubah keduanya identik; lihat aturan 6 di ui00)
- `app/templates/_upload_status.html`, `_import_progress.html`
- `app/templates/history.html`, `history_content.html`
- `app/templates/job_detail_content.html`, `_job_progress_fragment.html` (bila belum selesai di UI02)
- `app/static/css/theme-cinema.css` (komponen di bagian `/* upload */`, `/* history */`, `/* job */`)
- `app/core/translate.py` (kunci baru `ui.upload.*`, `ui.job.*`)

## Langkah

1. **Upload**: dua kartu (Upload File dan Download via link) menjadi dua panel bersisian. Kartu upload memakai tampilan **drop-zone**
   (border putus-putus, ikon, teks "Tarik video ke sini / Pilih file"). `<input type="file">` dan semua id/handler tetap; hanya dibungkus/di-class.
   Bila ada logika drag-drop di JS, jangan diubah; styling state `dragover` cukup lewat class yang sudah ditoggle JS (bila tidak ada, jangan menambah JS).
2. Form download (URL, opsi kualitas dll.) memakai gaya field gelap + tombol merah. Tombol/atribut tidak berubah.
3. **Status koneksi** TikTok (`#tiktok-connect-status`) dan Instagram (`#instagram-connect-status`) tampil sebagai pill kecil berwarna
   (hijau/emas/merah). JS yang mengisi elemen itu tidak diubah; bila JS membuat string markup dengan class `badge bg-*`/`alert-*`,
   sesuaikan class saja (aturan 5).
4. **Progres import/upload** (`_import_progress.html`, `_upload_status.html`, elemen progress di JS): progress merah bergradasi, teks persen jelas,
   pesan sukses/gagal memakai chip hijau/merah.
5. **History**: daftar/tabel menjadi baris kartu tipis dengan status berupa chip (`ok`, `wait`, merah untuk gagal), tanggal abu-abu,
   tombol aksi yang ada tetap. Pertahankan paginasi/filter bila ada.
6. **Job detail**: header job + progress besar, daftar langkah menjadi **stepper vertikal** (ikon status: selesai hijau, berjalan merah berdenyut halus,
   menunggu abu-abu). Binding `status.*` dan polling `hx-*` tidak berubah.

## Kriteria selesai

- `python scripts/ui_attr_audit.py check` lulus; peringatan perubahan `<script>` (bila ada) dijelaskan dan hanya menyentuh string class/markup.
- Upload file, download link, polling progres, dan navigasi riwayat/job bekerja seperti sebelum perubahan (uji manual, dilaporkan).
- `upload.html` dan `upload_content.html` menghasilkan tampilan sama.
- Responsif 360/768/1280 px: drop-zone, form, tabel riwayat (scroll di dalam wadah, bukan body), dan stepper job tidak overflow; tombol tidak bertumpuk/terpotong;
  nama file panjang terpotong rapi. Progress bar tetap terbaca (label persen tidak menimpa batang) pada layar sempit.
- State: tombol saat upload/download berjalan (disabled + spinner), error validasi URL/file kosong (gaya `.is-invalid`), dan empty state riwayat tampil benar.

## Jangan

- Jangan menggabungkan atau menghapus salah satu dari `upload.html`/`upload_content.html`. Jangan mengubah endpoint form.
