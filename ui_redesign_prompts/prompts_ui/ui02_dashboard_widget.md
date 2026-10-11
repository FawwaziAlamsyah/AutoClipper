# UI02 — Dashboard & Widget Job Global

> Prasyarat: UI01 selesai. Baca `ui00_urutan_dan_aturan.md`. Kerjakan HANYA task ini, lalu berhenti.

## Tujuan

Dashboard bergaya "billboard" Netflix dan widget job yang lebih rapi. Semua data, tombol, dan link yang ada tetap sama.

## File

- `app/templates/dashboard.html`, `app/templates/dashboard_content.html` (cek mana yang halaman penuh vs partial; hasil harus konsisten)
- `app/templates/_active_jobs_widget.html`, `app/templates/_job_progress_fragment.html`
- `app/static/css/theme-cinema.css` (tambah komponen khusus dashboard di bagian bawah, diberi komentar `/* dashboard */`)
- `app/core/translate.py` (kunci teks baru `ui.dash.*` di `en` dan `id`)

## Langkah

1. **Billboard hero** di atas konten: latar gradien (merah redup + biru redup seperti preview), eyebrow "Auto Clipper", judul besar,
   satu kalimat deskripsi, dan dua CTA. CTA **memakai link yang sudah ada**: tombol merah ke `/upload` (atribut `hx-get`, `hx-target`,
   `hx-push-url` dipindahkan apa adanya) dan tombol sekunder ke `/settings` (atau `/candidates` bila itu yang sudah ada di Quick Actions;
   jangan menambah rute). Teks lewat `t("ui.dash.*")`; jangan menghapus kunci lama yang masih dipakai.
2. **Empat kartu statistik** (Total Videos, Jobs Completed, Clips Generated, Pending Jobs) tetap memakai binding
   `stats.total_videos`, `stats.completed_jobs`, `stats.total_clips`, `stats.pending_jobs` dan kunci `dash.*` yang sama.
   Tampilan: tile kaca (`.stat-tile`) dengan angka besar 32px, label kecil abu-abu. **Jangan menambah indikator tren/angka** yang tidak disediakan backend.
3. **Quick Actions**: kedua aksi lama tetap ada (Upload/Download dan Settings), tampil sebagai dua tile besar dengan ikon `bi`, hover mengangkat
   halus dan border menyala. Atribut link tidak berubah.
4. **Widget job global** (`_active_jobs_widget.html`): toast gaya kaca di kanan bawah (`position-fixed`, aman terhadap `safe-area-inset-bottom`),
   judul "Processing Job #id", progress merah bergradasi dengan kilau halus, teks langkah + persen, link "lihat detail" tetap dengan `hx-*` yang sama.
   Pertahankan `id="global-widgets"` pada **kedua cabang** (`if`/`else`) dan struktur polling.
5. `_job_progress_fragment.html`: samakan gaya progress.
6. Empty state yang ramah bila `stats` bernilai 0 (hanya teks/ikon, tanpa data baru).

## Kriteria selesai

- `python scripts/ui_attr_audit.py check` lulus.
- Dashboard tampil sesuai preview (billboard + stats + quick actions); widget job muncul dan ter-update lewat polling seperti sebelumnya.
- Tampilan baik di lebar 360, 768, 1280 px.

## Jangan

- Jangan menambah endpoint/stat baru. Jangan mengubah `hx-trigger="load, every 3s"` pada `#global-widgets` di `base.html`.
