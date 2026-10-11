# UI05a — Halaman Detail Klip: Layout + Hapus Score Breakdown & Preview JSON

> Prasyarat: UI01–UI04 selesai. Baca `ui00_urutan_dan_aturan.md`. Kerjakan HANYA task ini, lalu berhenti.
> `candidate_detail_content.html` besar (±1450 baris, banyak inline style dan satu blok `<script>` besar).
> Task ini hanya **layout kerangka + penghapusan**; isi panel di `ui05b`.

## Tujuan

1. **Hapus** kartu Score Breakdown dan tombol Preview JSON (diminta user, karena tidak terpakai).
2. Susun halaman detail menjadi layout dua kolom ala Netflix: preview/pemutar besar di kiri, panel aksi di kanan.

## File

- `app/templates/candidate_detail_content.html`
- `app/static/css/theme-cinema.css` (bagian `/* detail */`)
- `app/core/translate.py` (hapus kunci yang tidak terpakai lagi, lihat di bawah)
- `scripts/ui_attr_allowlist.json` (**task ini satu-satunya yang boleh menambah allowlist**, hanya untuk penghapusan di bawah)

## Bagian A — Penghapusan (persis ini, tidak lebih)

Di `candidate_detail_content.html`, hapus seluruh blok dari komentar
`<!-- {{ t("candDetail.scoreBreakdown") }} — full width -->` sampai penutup `</div>` kartu itu, yang berisi:
judul, deskripsi (`candDetail.scoreDesc`), kotak info "Skor dihitung pakai…", tabel analyzer
(`{% for name, value in breakdown.items() %}` … `candDetail.noBreakdown`), dan link
`<a … href="/preview/candidates/{{ candidate.id }}">{{ t("candDetail.previewJson") }}</a>`.

Setelah dihapus:
- Pastikan tidak ada elemen/JS lain di file yang membaca `breakdown` (cari `breakdown` di seluruh `app/templates`). Bila ada, laporkan dan jangan menebak.
- Tambahkan ke `ui_attr_allowlist.json` untuk file ini: `"href:/preview/candidates/{{ candidate.id }}"` dan kunci terjemahan
  `candDetail.scoreBreakdown`, `candDetail.scoreDesc`, `candDetail.noBreakdown`, `candDetail.previewJson`, serta kunci tabel
  (`candDetail.analyzer`, `candDetail.score`, `candDetail.weight`, `candDetail.contribution`, `candDetail.reason`) **hanya jika** `grep -r` membuktikan
  tidak dipakai di template/JS/py lain.
- Di `app/core/translate.py`, hapus kunci-kunci di atas dari dict `en` **dan** `id` **hanya** bila terbukti tidak terpakai di tempat lain.
- **Jangan** menghapus/ubah: route `/preview/candidates/{id}` (JSON) maupun `/preview/candidates/{id}/clip` (dipakai pemutar video),
  context `breakdown` di `candidate_router.py`, kolom `score_breakdown`, atau skema/model. Backend dibiarkan; catat di laporan bahwa
  `breakdown` kini tidak dipakai template.
- **Jangan** menambah pengganti (tabel/ringkasan analyzer baru). `candidate.final_score` tetap ditampilkan sebagai badge skor di header.

## Bagian B — Layout dua kolom

Target (lihat bagian "Detail klip" di `docs/ui/preview.html`):
- **Header halaman** (kartu paling atas): judul "Candidate #id", rentang `Window: start–end`, kutipan `hook_text` (bila ada), badge skor
  (`final_score`, hijau) dan chip status. Isi lama tetap ada; hanya ditata.
- **Grid** `detail-grid`: kolom kiri (±62%) dan kanan (±38%) pada ≥ 992px; satu kolom pada layar kecil (urutan: pemutar/preview → aksi).
  - **Kolom kiri**: area preview/pemutar dan kartu **Edit Clip** (kartu yang memuat `_clip_edit_preview.html`).
  - **Kolom kanan** (`position: sticky; top: 84px` pada desktop): kartu **Render Clip** (termasuk blok TikTok dan Instagram di dalamnya) dan kartu **Subtitle**.
- Pindahkan **kartu utuh** (jangan memecah isi kartu). Urutan elemen interaktif di dalam kartu tidak berubah.
  Jika memindahkan sebuah kartu mengubah urutan DOM, pastikan tidak ada JS yang bergantung pada urutan sibling
  (`nextElementSibling`, `previousElementSibling`, `parentElement` bertingkat, `querySelector` relatif posisi) — periksa blok `<script>` dan laporkan.
- Semua `id`, `onclick`, `hx-*`, `data-*`, dan blok `<script>` tidak diubah (peringatan hash script harus **nol** di task ini).
- Pindahkan inline `style=""` statis yang berada di kerangka layout (bukan di dalam isi panel) menjadi class.

## Kriteria selesai

- `python scripts/ui_attr_audit.py check` lulus dengan hanya entri allowlist di atas sebagai penghapusan; tidak ada peringatan `<script>`.
- Halaman detail tidak lagi menampilkan Score Breakdown maupun Preview JSON; `grep -rn "previewJson\|scoreBreakdown" app/templates` kosong.
- Semua kartu lain (Render, Edit, Subtitle) masih ada dan berfungsi: render klip, edit, subtitle, kirim TikTok, kirim Instagram (uji manual, dilaporkan).
- Desktop: dua kolom dengan kolom kanan sticky; mobile: satu kolom rapi.

## Jangan

- Jangan menyentuh isi panel (itu `ui05b`). Jangan mengubah backend. Jangan menghapus apa pun selain yang tertulis di Bagian A.
