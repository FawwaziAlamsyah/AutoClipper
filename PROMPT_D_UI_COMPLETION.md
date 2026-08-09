# Prompt D — Lengkapi UI agar Memakai Semua Fitur Backend

Konteks: backend sudah punya banyak fitur (analysis breakdown, subtitle, preview,
job steps) yang belum semuanya ditampilkan di UI. Template yang ada sekarang cuma:
`base.html`, `dashboard.html`, `upload.html`, `candidates.html`, `history.html`,
dan `index.html` (yang ternyata tidak terpakai — halaman `/` merender
`dashboard.html`, bukan `index.html`). Kerjakan Tahap A, B, C dulu sebelum tahap
ini, supaya UI menampilkan data yang sudah benar/jujur dari backend.

## Yang Harus Dikerjakan

1. **Bersihkan template yang tidak terpakai.**
   Hapus `app/templates/index.html` (dead file), atau kalau memang masih mau
   dipakai sebagai landing page terpisah dari dashboard, sambungkan route-nya.

2. **Halaman detail candidate.**
   Tambah halaman/section yang menampilkan `score_breakdown` per analyzer untuk
   satu candidate (bukan cuma angka `final_score` di tabel seperti sekarang di
   `candidates.html`) — supaya user bisa lihat kenapa suatu klip diberi skor
   tertentu.

3. **Halaman preview & pemilihan subtitle.**
   `subtitle_service.py`/`subtitle_router.py` sudah ada di backend tapi belum
   ada UI-nya. Tambah tampilan untuk melihat/pilih format subtitle (srt/vtt)
   sebelum render final clip.

4. **Halaman progress tracker per job.**
   Berdasarkan endpoint yang diperluas di Prompt C (`GET /jobs/{job_id}`), buat
   tampilan step-by-step (status, persentase, waktu mulai/selesai/durasi) —
   bisa jadi halaman baru `job_detail.html`, atau perluasan panel progress yang
   sudah ada di `upload.html`.

5. **Halaman pengaturan sederhana (opsional, prioritas terakhir).**
   Form untuk mengubah `SCORE_WEIGHT_*` dan API key LLM tanpa perlu edit `.env`
   manual + restart server. Kalau belum mau overengineer, cukup tampilkan nilai
   `SCORE_WEIGHT_*` yang sedang aktif sebagai read-only di halaman candidate
   detail (poin 2), pengaturan bisa menyusul nanti.

## Definisi Selesai

- Tidak ada template mati (`index.html` sudah dibersihkan/disambungkan).
- User bisa melihat alasan skor tiap candidate, bukan cuma angka akhir.
- User bisa preview/pilih subtitle dari UI, tidak perlu lewat API langsung.
- User bisa melihat progress job step-by-step dari UI, sesuai data nyata dari
  Prompt C — bukan daftar step yang aspirational/tidak sinkron dengan backend.
