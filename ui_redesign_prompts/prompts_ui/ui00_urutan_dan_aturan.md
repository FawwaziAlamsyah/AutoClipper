# UI Redesign "Cinema" — Urutan Task, Aturan, dan Design Tokens

Rombak UI/UX AutoClipper menjadi **tema gelap bergaya Netflix**. Ini hanya perubahan tampilan.

## Cara pakai (untuk agent)

1. Kerjakan task **berurutan**, **satu task per sesi**. Jangan menyentuh file di luar daftar task.
2. Baca dulu `.agents/rules/guidelines.md`, `architecture.md`, dan file ini.
3. **Referensi visual**: `docs/ui/preview.html` (halaman preview yang sudah disetujui user; salin dari
   `autoclipper_ui_preview.html`). CSS di dalamnya adalah sumber kebenaran untuk warna, radius, jarak,
   gaya kartu/tombol/badge/panel. Tiru tampilannya, jangan menyalin teks/data dummy-nya.
4. Setelah tiap task: jalankan `python scripts/ui_attr_audit.py check` (dibuat di UI01), pastikan lulus,
   jalankan test yang terkait saja, lalu beri laporan singkat dan **berhenti**.

| # | File | Isi |
|---|------|-----|
| 01 | `ui01_fondasi_tema.md` | `theme-cinema.css`, `base.html`, skrip audit atribut, default tema dark |
| 02 | `ui02_dashboard_widget.md` | Dashboard + widget job global |
| 03 | `ui03_upload_history_job.md` | Upload, History, Job detail |
| 04 | `ui04_candidates.md` | Daftar candidates, kartu klip, arsip |
| 05a | `ui05a_detail_layout.md` | Halaman detail klip: layout + **hapus Score Breakdown & Preview JSON** |
| 05b | `ui05b_detail_panels.md` | Panel render/edit/subtitle/TikTok/Instagram |
| 06 | `ui06_settings_training_storage_legal.md` | Settings, Training, Storage, halaman legal |
| 07 | `ui07_polish.md` | Animasi, status pill, responsif, aksesibilitas, audit akhir |

## ATURAN KERAS (berlaku di semua task)

1. **Jangan hapus atau ubah fungsi.** Semua tombol, form, link, dan perilaku yang ada harus tetap ada dan bekerja.
2. **Jangan ubah** atribut fungsional: `id`, `name`, `for`, `onclick`/`on*`, `hx-*`, `data-*`, `href`/`action`/`src`
   (termasuk ekspresi Jinja-nya), `type`, `value`, `target`, serta isi tag `<script>` (kecuali bagian yang
   disebut jelas di task, atau string markup/class di dalam JS yang membuat elemen UI — lihat aturan 5).
3. **Boleh diubah**: class CSS, struktur pembungkus (`div` layout), urutan visual lewat CSS, ikon, teks label via `t()`
   (tambah kunci baru di `en` dan `id` pada `app/core/translate.py`; jangan menghapus kunci yang masih dipakai).
4. **Backend tidak disentuh.** Satu-satunya pengecualian di seluruh rangkaian: default tema
   `APP_DEFAULT_THEME` menjadi `"dark"` (UI01). Jangan ubah router/service/model/skema/migrasi. Jangan menambah endpoint.
   Jangan menampilkan data baru yang belum disediakan backend (tidak ada angka/tren karangan).
5. Jika JS membuat HTML dengan class Bootstrap lama (mis. `progress-bar`, `alert alert-*`, `badge bg-*`),
   **hanya class/markup string** yang boleh disesuaikan agar serasi tema. Logika, selector `getElementById`, dan
   alur fetch tidak boleh berubah. Setiap perubahan JS dilaporkan.
6. `upload.html` dan `upload_content.html` memuat konten yang serupa (halaman penuh vs partial HTMX): ubah
   **keduanya** dengan hasil identik; jangan digabung.
7. Pertahankan `{% extends %}`, `{% block %}`, `{% include %}`, dan pola navigasi HTMX (`hx-get`, `hx-target="#main-content"`,
   `hx-push-url`). Elemen `#main-content` dan `#global-widgets` (polling tiap 3 detik) tidak boleh berubah perilakunya.
8. Hindari inline `style=""` baru; pindahkan ke class di `theme-cinema.css`. Inline style lama boleh dipertahankan
   bila dinamis (mis. `width: {{ percent }}%`).
9. Tidak ada library baru kecuali yang disebut di UI01 (font Inter dan Bootstrap Icons via CDN, versi dipin).
10. Aksesibilitas minimum: kontras teks ≥ 4.5:1, `:focus-visible` terlihat, `prefers-reduced-motion` dihormati,
    target sentuh ≥ 36px untuk tombol utama.
11. **Hierarki candidates tidak berubah**: daftar video/upload → candidate milik video itu → detail candidate. Candidate tidak boleh
    dicampur lintas video atau dipindah ke halaman lain (lihat `ui04_candidates.md`). Elemen "baris" di `docs/ui/preview.html` hanya
    contoh gaya kartu; di aplikasi, baris/grid kartu hanya berisi candidate dari **satu** video.

## CHECKLIST DETAIL KECIL (wajib dilalui di setiap task, dicentang di laporan)

- [ ] **Progress bar**: semua bar yang disentuh task (statik maupun dibuat JS) memakai gaya tema, label persen terbaca, warna sesuai status (merah=berjalan, hijau=selesai, emas=menunggu, merah gelap=gagal).
- [ ] **Responsif** di 360, 414, 768, 1024, 1280 px: tidak ada scroll horizontal di body, tabel/kode panjang scroll di wadahnya, tombol tidak terpotong/bertumpuk.
- [ ] **State**: hover, focus-visible, active, disabled, loading (spinner/HTMX), error/validasi, dan **empty state** untuk setiap kontrol/daftar yang disentuh.
- [ ] **Teks panjang**: nama file, URL, hook, pesan error tidak merusak layout (ellipsis atau wrap).
- [ ] **Sentuh**: target ≥ 36px; input ≥ 16px di mobile; elemen yang hanya muncul saat hover tetap terlihat di layar sentuh.
- [ ] **Overlay**: toast/dropdown/modal tidak tertutup navbar sticky dan tidak keluar layar; `z-index` konsisten.
- [ ] **Video/gambar**: tidak terdistorsi/terpotong (`object-fit: contain` untuk video klip); rasio kotak tetap stabil (tanpa layout shift).
- [ ] **Kontras & fokus**: teks ≥ 4.5:1, cincin fokus terlihat, animasi mati bila `prefers-reduced-motion`.
- [ ] **Audit**: `python scripts/ui_attr_audit.py check` lulus.

## Yang SENGAJA dihapus (diminta user)

Hanya di halaman detail klip (dikerjakan di `ui05a`):
- Seluruh kartu **Score Breakdown** (tabel analyzer, kotak "Skor dihitung pakai", deskripsi, pesan "Belum ada breakdown").
- Tombol/link **Preview JSON** (`/preview/candidates/{id}` dengan label `candDetail.previewJson`).
Route dan data backend-nya **dibiarkan** (tidak dihapus). Selain dua hal ini, tidak ada yang boleh dihapus.

## Design tokens (harus sama dengan `docs/ui/preview.html`)

```
--canvas:#141414  --bg:#0b0b0c  --surface:#1c1c1e  --surface-2:#242426  --surface-3:#2e2e31
--line:rgba(255,255,255,.08)  --line-strong:rgba(255,255,255,.16)
--text:#f5f5f1  --muted:#a3a3a8  --faint:#6e6e73
--red:#e50914  --red-hover:#f6121d  --red-deep:#b9090b
--green:#46d369  --gold:#e5b34a  --blue:#4aa8ff
--radius:10px  --radius-lg:16px
font: Inter, 'Helvetica Neue', 'Segoe UI', Roboto, Ubuntu, sans-serif
```
Prinsip: merah **hanya** untuk aksi utama, indikator aktif, progres, dan wordmark. Kedalaman lewat tingkat permukaan
+ border tipis, bukan bayangan. Hijau = sukses/skor, emas = menunggu/peringatan. Instagram dan TikTok punya warna
sendiri hanya pada tombol/badge platform.
