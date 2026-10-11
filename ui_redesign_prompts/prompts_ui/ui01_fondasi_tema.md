# UI01 — Fondasi Tema Cinema (CSS, base layout, skrip audit)

> Baca `ui00_urutan_dan_aturan.md` dulu (aturan keras). Kerjakan HANYA task ini, lalu berhenti.

## Tujuan

Pasang sistem desain gelap bergaya Netflix sebagai fondasi untuk semua halaman, tanpa mengubah fungsi.
Buat juga **skrip audit atribut** yang menjaga agar tidak ada tombol/fungsi yang hilang selama rombakan.

## File

**Baru**
- `app/static/css/theme-cinema.css`
- `app/static/js/ui.js` (kecil, tanpa dependensi, hanya perilaku tampilan)
- `scripts/ui_attr_audit.py`, `scripts/ui_attr_baseline.json`, `scripts/ui_attr_allowlist.json`
- `tests/unit/test_ui_attr_audit.py`
- `docs/ui/preview.html` (salinan `autoclipper_ui_preview.html` dari user; bila belum ada, minta user menaruhnya)

**Ubah**
- `app/templates/base.html`
- `app/static/css/style.css` (pertahankan aturan lama `.table .btn` dan `.htmx-indicator`; pindahkan warna body ke tema)
- `app/core/config/settings.py` — `APP_DEFAULT_THEME: str = "dark"` (SATU-SATUNYA perubahan backend)
- `.env.example` bila ada baris tema

## Langkah

### 0. Snapshot baseline (SEBELUM mengubah template apa pun)
Buat `scripts/ui_attr_audit.py` dulu, jalankan `python scripts/ui_attr_audit.py snapshot` pada template saat ini,
commit `ui_attr_baseline.json`. Skrip:
- Memindai `app/templates/**/*.html`. Untuk tiap file merekam (sebagai himpunan): semua `id="…"`, `name="…"`,
  `for="…"`, atribut `hx-*` (nama + nilai), atribut `on*` (nama + nilai, spasi dinormalisasi), `data-*` (nama + nilai),
  nilai `href`/`action`/`src` yang mengandung `{{`, `{%`, atau diawali `/`, semua `{% extends/include/block %}`,
  semua kunci `t("…")`, dan **hash isi tiap `<script>`**.
- `check`: bandingkan template sekarang dengan baseline. **Gagal (exit 1)** bila ada yang HILANG (id, name, hx-*, on*,
  data-*, href/action, include/extends, kunci t()) kecuali tercantum di `ui_attr_allowlist.json`
  (format `{ "file.html": ["id:foo", "href:/preview/candidates/{{ candidate.id }}"] }`). Yang ditambahkan = OK.
  Perubahan hash `<script>` = **WARNING** (dicetak dengan nama file) yang wajib dijelaskan di laporan.
- `snapshot` hanya boleh dijalankan manual untuk membuat ulang baseline; task lain tidak boleh menimpa baseline.
- Test unit kecil memakai folder template sementara: hilang id → gagal; tambah id → lulus; allowlist → lulus.

### 1. `theme-cinema.css`
Ikuti token di `ui00` dan `docs/ui/preview.html`. Struktur: tokens (`:root` + `[data-bs-theme="dark"]` dan versi terang
sederhana di `[data-bs-theme="light"]` agar toggle tema yang ada tetap berfungsi), reset ringan, lalu override Bootstrap
dengan memetakan CSS variable Bootstrap (`--bs-body-bg`, `--bs-body-color`, `--bs-border-color`, `--bs-card-bg`, `--bs-table-*`,
`--bs-primary`/`--bs-primary-rgb`, dll.) ke token. Komponen yang harus di-restyle:
- **Tombol:** `.btn-primary` = merah Netflix (hover `--red-hover`, glow lembut); `.btn-secondary`/`.btn-outline-secondary` = abu-abu
  transparan; `.btn-outline-*` (info/danger/success/warning) = outline tipis berwarna selaras; `.btn-danger` outline merah;
  `.btn-sm` tetap kompak. Ada `:active` scale 0.97.
- **Kartu:** `.card` memakai `--surface`, border `--line`, radius `--radius-lg`; **hapus efek `.shadow-sm`** (set none) — kedalaman
  lewat border dan tingkat permukaan. Hover kartu tidak otomatis (hover khusus ada di UI04).
- **Form:** input/select/textarea gelap (`#0f0f10`), border `--line-strong`, fokus cincin merah transparan; `.form-check`/switch merah saat aktif.
- **Tabel:** transparan, header kecil huruf kapital abu-abu, garis `--line`, hover baris halus; matikan striped terang.
- **Badge:** nada lembut (latar tint 14–16% + teks warna) untuk `bg-success/info/warning/danger/secondary/dark/light`; badge `text-dark`
  harus tetap terbaca.
- **Alert, progress (gradien merah, tinggi 6px; varian `bg-success` hijau, `bg-warning` emas, `bg-danger` merah gelap; label persen terbaca), toast, modal,
  dropdown, list-group, nav-tabs/pills, accordion, spinner, close button.**
- **Komponen yang mudah terlewat:** tooltip dan popover (gelap, panah menyesuaikan), pagination, breadcrumb, input-group, btn-group, offcanvas, placeholder/skeleton,
  badge pill, `<hr>`, `<code>`/`<pre>` (latar `#0f0f10`), `<details>`, link teks (warna, hover, underline offset), dan tabel `.table-responsive` (scrollbar tipis).
- **State interaktif untuk SEMUA kontrol:** `:hover`, `:focus-visible`, `:active`, **`:disabled`/`.disabled`** (opacity ±.45, kursor `not-allowed`, tanpa glow),
  **loading** (tombol dengan `.spinner-border-sm` tetap terbaca; elemen `.htmx-request`), **validasi form** (`.is-invalid` merah + `.invalid-feedback`, `.is-valid` hijau),
  `readonly`, dan `placeholder` (kontras cukup).
- **Dasar responsif:** font input/select/textarea **minimal 16px** di layar sentuh (mencegah zoom otomatis iOS); target sentuh tombol utama ≥ 36–40px;
  body tidak boleh punya scroll horizontal; teks panjang (nama file, URL, hook) dipotong dengan `text-overflow: ellipsis` atau `overflow-wrap: anywhere` sesuai konteks;
  `scroll-padding-top` setinggi navbar agar anchor/fokus tidak tertutup navbar sticky; hindari `100vh` mentah di mobile (pakai `100dvh`/`min-height` dengan fallback).
- **Dialog bawaan browser** (`confirm()`/`alert()`) tidak bisa di-style dan **tidak diganti** (mengganti berarti mengubah JS). Biarkan apa adanya.
- Scrollbar tipis gelap, `::selection` merah transparan, `:focus-visible` cincin jelas, `prefers-reduced-motion`.
- Utility kecil yang akan dipakai task lain: `.page-head`, `.section-label`, `.surface`, `.chip` (+ varian `ok/wait/ig/tt`),
  `.stat-tile`, `.panel` (kartu panel seperti di preview), `.glass`.

### 2. `base.html`
- `<head>`: tambahkan font Inter (Google Fonts, `display=swap`), **Bootstrap Icons 1.11.3** CSS (pinned; saat ini ikon `bi bi-*` dipakai di
  template tetapi library-nya belum dimuat), `theme-cinema.css` setelah Bootstrap dan `style.css`, `ui.js` dengan `defer`.
  Tambahkan `<meta name="theme-color" content="#141414">` dan `viewport-fit=cover`. **Jangan** ubah skrip HTMX (integrity) maupun `I18N`.
- Navbar: ubah menjadi bar tetap/sticky di atas, transparan bergradasi lalu **solid + blur** setelah scroll (class `solid` ditoggle `ui.js`).
  Wordmark `{{ app_name }}` huruf kapital tebal merah. **Semua link nav dan atribut `hx-*` tidak berubah**; hanya class.
  Link aktif diberi class `active` (garis merah bawah): `ui.js` mencocokkan `location.pathname` saat load dan setiap
  `htmx:pushedIntoHistory`/`htmx:afterSettle`.
- Pertahankan collapse mobile (`navbar-toggler`, `data-bs-*`).
- `#global-widgets` tetap persis (atribut `hx-get`, `hx-trigger`, `hx-swap`), di luar `#main-content`.
- `#main-content`: container lebih lebar (maks ±1360px), padding responsif.
- Footer minimal: border atas tipis, teks `--faint`, link legal tetap.
- Body: `data-bs-theme="{{ theme }}"` tetap.

### 3. `ui.js`
Hanya: toggle class `solid` pada navbar saat scroll, penanda link aktif, dan handler panah scroll horizontal untuk
`.row-scroller` (dipakai UI04). Tanpa fetch, tanpa state, aman bila elemen tidak ada.

## Kriteria selesai

- `python scripts/ui_attr_audit.py check` lulus (tidak ada yang hilang). Test `tests/unit/test_ui_attr_audit.py` lulus.
- Semua halaman (`/`, `/upload`, `/candidates`, detail candidate, `/settings`, `/training/dashboard`, `/storage/dashboard`, history)
  tampil gelap, terbaca, tanpa error konsol; ikon `bi` muncul; navigasi HTMX tetap jalan dan link aktif ter-update.
- Toggle tema terang (bila ada di Settings) tidak merusak tata letak.
- Tidak ada perubahan backend selain nilai default tema.

## Jangan

- Jangan restyle per-halaman di task ini (itu UI02–UI07) kecuali yang disebut di atas.
- Jangan menimpa `ui_attr_baseline.json` setelah dibuat. Jangan mengubah `ui_attr_allowlist.json` kecuali oleh task yang secara eksplisit menyebutnya.
