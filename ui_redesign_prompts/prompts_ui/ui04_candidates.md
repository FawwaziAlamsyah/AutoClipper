# UI04 — Candidates: Kartu Video, Kartu Klip, Arsip

> Prasyarat: UI01–UI03 selesai. Baca `ui00_urutan_dan_aturan.md`. Kerjakan HANYA task ini, lalu berhenti.

## Tujuan

Halaman candidates terasa seperti rak film Netflix: kartu berskala saat hover, thumbnail 16:9, badge status rapi.
Semua tombol (Detail, Hapus, like/dislike, arsip) dan perilaku yang ada tetap.

## STRUKTUR WAJIB DIPERTAHANKAN (permintaan user)

Candidates **tetap dikelompokkan per upload (video ID)** dengan tiga level navigasi seperti sekarang. Rombakan hanya tampilan:

1. `/candidates` — daftar **video/upload** (satu kartu per video, memuat ringkasan candidates-nya).
2. `/candidates/video/{video_id}` — daftar **candidate milik video itu saja**.
3. `/candidates/{candidate_id}` — **detail** satu candidate (isi dan fungsinya sama seperti sekarang).

Larangan: jangan menggabungkan level, jangan membuat daftar candidate lintas-video (mis. baris "Siap dikirim" atau "Top score" yang
mencampur beberapa video), jangan mengubah route, query, maupun pengelompokan data. Candidate hanya muncul di dalam halaman videonya.
Navigasi antar level memakai link/`hx-*` yang sudah ada. Tambahkan **breadcrumb visual** (mis. `Candidates › {nama video} › Candidate #id`)
di level 2 dan 3 **hanya memakai link yang sudah ada** (link kembali ke daftar video/daftar candidate video); breadcrumb tidak boleh
menggantikan atau menghapus link/tombol kembali yang ada. Arsip (`/candidates/archived`) tetap sebagai halaman terpisah dengan struktur sama.

## File

- `app/templates/candidates_content.html` (daftar video + ringkasan)
- `app/templates/candidates_video_content.html` (daftar candidate per video)
- `app/templates/candidates_archived_content.html`
- `app/templates/_candidate_row.html`, `_rating_control.html`
- `app/static/css/theme-cinema.css` (bagian `/* candidates */`), `app/static/js/ui.js` (hanya panah scroll bila dipakai)
- `app/core/translate.py` (kunci `ui.cand.*`)

## Langkah

1. **Kartu video** (`candidates_content.html`): kartu dengan area thumbnail bergradasi (gradien deterministik dari `video.id` via class
   `g-1…g-6`, **tanpa data baru**), judul `original_filename` terpotong, chip: jumlah candidates, Top score, clip dibuat, 👍/👎, durasi, jenis sumber.
   Tombol "lihat" (link `/candidates/video/{id}` dengan `hx-*`) tetap; seluruh kartu boleh klikable HANYA bila tidak menggandakan atribut `hx-*`
   (cukup tombol yang ada diperbesar area kliknya lewat `stretched-link` bila aman).
2. **Header halaman**: judul + subjudul + tombol Arsip memakai `.page-head`; tombol arsip dan link-nya tidak berubah.
3. **Kartu klip** (`_candidate_row.html`): thumbnail = elemen `<video controls preload="metadata">` yang sudah ada (jangan diganti), rasio 16:9 dengan latar hitam dan `object-fit: contain` (klip vertikal 9:16/1:1 **tidak boleh terpotong atau terdistorsi**),
   badge durasi kanan-bawah, **badge skor** kiri-atas (`candidate.final_score`, hijau). Judul = `hook_text` atau "Candidate #id".
   Chip status: `clip ready`, `Generated`, `TikTok ✓`, `Instagram ✓` (ada `candidate.instagram_published`) dengan warna platform.
   Baris aksi (Detail, Hapus, rating) **muncul/diperjelas saat hover** pada perangkat yang mendukung hover
   (`@media (hover:hover)`), dan **selalu terlihat** pada layar sentuh. Hover desktop: `transform: scale(1.04)` + border terang, transisi ≤ 280ms.
   Pertahankan `id="row-{{ candidate.id }}"`, `id="like-status-{{ candidate.id }}"`, `onclick="deleteCandidate(...)"` dan `data-candidate-id`.
4. **Rating** (`_rating_control.html`): tombol like/dislike berbentuk pill ikon; status aktif berwarna hijau/merah. Atribut `hx-*`/`onclick` tidak berubah.
5. **Layout kartu klip (level 2) — JANGAN DIPERBESAR**: ukuran kartu sama seperti di `docs/ui/preview.html` (lebar kartu `clamp(240px, 23vw, 320px)`,
   thumbnail 16:9, padding body 12–14px). Tampilkan kartu dalam **satu baris geser horizontal** (`.row-scroller` + panah kiri/kanan dari `ui.js`,
   scroll-snap) sebagaimana di preview; jangan membuat kartu melebar mengisi ruang (tidak ada `1fr` yang meregangkan kartu).
   Pada layar sentuh baris bisa digeser dengan jari. Bila template saat ini memakai `row g-3` + `col-*` Bootstrap, ganti hanya pembungkusnya
   (kelas kolom tidak boleh dipakai JS) dan pertahankan semua `id` kartu.
   **Data/logika**: level 2 menampilkan **SEMUA candidate yang sudah di-generate untuk video itu** persis dari data yang sudah dikirim backend
   (jumlah mengikuti data, mis. 5, 12, atau 40) — jangan membatasi ke "top N", jangan menambah paginasi/filter, jangan memakai data contoh dari preview.
   Judul section memakai jumlah nyata (`{{ candidates | length }} candidates`, sesuaikan dengan variabel yang sudah ada). Urutan candidate tidak diubah.
   Jangan membuat pengelompokan baru (mis. per status atau per skor). Header level 2 menampilkan identitas video (nama file, ID, durasi, jumlah candidates)
   dari data yang sudah ada.
6. **Arsip**: gaya sama, kartu lebih redup (opacity ~.85), tombol restore/hapus yang ada tetap.
7. **Empty state**: ilustrasi ikon + teks bila tidak ada data.

## Kriteria selesai

- `python scripts/ui_attr_audit.py check` lulus.
- Kartu klip dapat diputar, dihapus, di-like/dislike, dan dibuka detailnya seperti sebelumnya; update HTMX pada `#like-status-{id}` dan `#row-{id}` bekerja.
- Hover tidak menyebabkan layout bergeser/terpotong (kartu paling kanan/kiri tidak terpotong; gunakan `z-index` dan padding kontainer).
- Tampilan baik di 360/768/1280 px; nama file/hook panjang terpotong rapi; chip yang banyak membungkus ke baris baru tanpa merusak kartu;
  baris geser horizontal bisa digeser dengan sentuh dan panah di desktop, dan tidak menimbulkan scroll horizontal pada body.

## Jangan

- Jangan mengganti `<video>` dengan gambar, jangan mengubah URL sumber video, jangan mengubah query/handler hapus.
