# UI06 — Settings, Training, Storage, Halaman Legal

> Prasyarat: UI01–UI05b selesai. Baca `ui00_urutan_dan_aturan.md`. Kerjakan HANYA task ini, lalu berhenti.

## Tujuan

Halaman pengaturan dan administrasi terlihat selaras dengan tema: bagian-bagian yang jelas, form gelap yang nyaman,
tabel rapi. Semua form, switch, tombol, dan skrip tetap sama.

## File

- `app/templates/settings.html` (±320 baris, ada `<script>` dan `{% block scripts %}`)
- `app/templates/training_dashboard_content.html`, `training_import.html`
- `app/templates/storage_dashboard_content.html`
- `app/templates/privacy_policy.html`, `terms_of_service.html`
- `app/static/css/theme-cinema.css` (bagian `/* settings */`, `/* training */`, `/* storage */`, `/* legal */`)
- `app/core/translate.py` (kunci `ui.settings.*`, `ui.storage.*` bila perlu)

## Langkah

1. **Settings**: judul halaman besar + subjudul; setiap kelompok pengaturan menjadi `.panel` bertajuk (ikon + judul + deskripsi kecil), dua kolom pada desktop.
   Field/select/switch memakai gaya tema; tombol simpan merah. Kontrol bahasa/tema yang ada tetap berfungsi (cookie `daboclip_pref`). Spinner/indikator HTMX tetap.
   Bagian status koneksi (TikTok/Instagram) bila ada ditampilkan sebagai kartu dengan chip hijau/emas/merah.
2. **Training dashboard**: kartu statistik model (`.stat-tile`), tabel riwayat/dataset bergaya tema, tombol aksi (train/import/dll.) tetap;
   progres training memakai progress merah. `training_import.html`: area unggah CSV bergaya drop-zone seperti UI03, kartu format CSV memakai `<code>` gelap.
3. **Storage dashboard**: penggunaan disk sebagai bar progress dengan ambang warna (hijau/emas/merah) **berdasarkan nilai yang sudah dihitung template** —
   jangan menghitung ulang di backend; bila ambang tidak tersedia, pakai satu warna. Tabel/daftar file bergaya tema; tombol bersihkan/hapus tetap
   dengan konfirmasi yang sudah ada.
4. **Legal** (privacy, terms): teks panjang dalam kontainer sempit (maks ~720px), tipografi nyaman (line-height 1.7), heading berhirarki, kontras tinggi.
5. Empty state dan pesan error/sukses (alert) diseragamkan lewat class tema.

## Kriteria selesai

- `python scripts/ui_attr_audit.py check` lulus.
- Simpan pengaturan, ganti bahasa/tema, jalankan aksi training/import, dan aksi storage bekerja seperti sebelumnya (uji manual, dilaporkan).
- Tidak ada overflow horizontal pada 360px.

## Jangan

- Jangan mengubah nama field/endpoint form, urutan field, atau logika JS pada `settings.html`.
