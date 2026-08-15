# Instruksi Umum: Membaca & Menerapkan File Spesifikasi (.md)

Gunakan prompt ini SETIAP kali menyerahkan file `.md` (spesifikasi/prompt
perbaikan apa pun) ke AI untuk dikerjakan — tempel prompt ini duluan,
sebelum atau bersama file `.md`-nya. Berlaku untuk 1 file `.md` apa pun,
bukan cuma seri tertentu.

## Sebelum Mulai

1. **Baca seluruh file `.md` sampai habis dulu** sebelum mengubah kode
   apa pun — termasuk bagian "Konteks" di awal file (sering menjelaskan
   KENAPA perubahan ini perlu, bukan cuma APA yang harus diubah).
2. Kalau file itu menyebut **prasyarat** (misal "kerjakan file X dulu kalau
   belum"), cek dulu apakah prasyarat itu sudah ada di codebase saat ini.
   Kalau belum, **berhenti dan laporkan** — jangan coba kerjakan file ini
   duluan lalu "nebak-nebak" bagian yang bergantung ke prasyarat tadi.
3. Pastikan bisa jalankan `pytest` dan `python -m py_compile` di environment
   ini sebelum mulai — dipakai untuk verifikasi di akhir, bukan cuma basa-basi.

## Saat Mengerjakan

4. **Ikuti urutan Task di file itu sesuai urutan tertulis** (Task 1 → 2 → 3
   dst) — jangan loncat ke task yang kelihatan lebih menarik/mudah duluan.
   Kalau file itu bagian dari beberapa file bernomor/berlabel (A/B/C,
   1/2/3, dst), kerjakan urut sesuai nomor labelnya juga.
5. **Salin snippet kode yang diberikan apa adanya** kalau ada — jangan
   ditulis ulang dengan gaya sendiri kecuali memang diminta menyesuaikan
   dengan kode yang sudah ada. Snippet di file itu sudah disesuaikan
   dengan konteks project, bukan contoh generik.
6. Kalau ada bagian yang eksplisit ditandai **"butuh keputusan Anda"**,
   **"opsional"**, atau semacamnya — JANGAN asumsikan jawabannya sendiri.
   Berhenti, tanyakan dengan opsi yang jelas, baru lanjut setelah dijawab.
7. Perhatikan bagian **"Catatan Khusus"** atau **"JANGAN ubah ini"** kalau
   ada di file itu — itu bukan bagian dari task, itu pengingat supaya
   sesuatu yang MUNGKIN kelihatan seperti bug/kelupaan sebenarnya memang
   disengaja. Jangan "perbaiki" sesuatu yang ditandai begitu.

## Setelah Selesai

8. Jalankan checklist **"Definisi Selesai"** di akhir file **satu per
   satu, nyata** (jalankan perintahnya/cek manual) — jangan diasumsikan
   lulus tanpa dicoba.
9. Jalankan `pytest` penuh — harus tetap hijau. Kalau ada test yang gagal
   akibat perubahan ini, investigasi dulu sebelum lapor selesai — jangan
   ubah test supaya lulus paksa kecuali memang itu yang diminta.
10. **Laporkan hasil akhir**, format:

```
## Selesai: <nama file .md>

### Perubahan
- <file>:<baris> — <ringkas apa yang diubah>
- ...

### Hasil verifikasi "Definisi Selesai"
- <item 1>: lulus/gagal — <detail singkat>
- ...

### Hasil pytest
<pass/fail, jumlah test>

### Temuan di luar scope file ini?
<ya, jelaskan — atau: tidak ada>
```

## Aturan Tambahan

- **Jangan perluas scope sendiri.** Kalau saat mengerjakan nemu bug/dead
  code/perbaikan lain yang TIDAK disebutkan di file `.md` ini, jangan
  langsung diubah — laporkan sebagai temuan tambahan di bagian akhir,
  biar user yang putuskan mau ditangani sekarang atau nanti.
- **Satu perubahan logis, satu potongan diff** — jangan gabungkan banyak
  task jadi satu blok perubahan besar yang susah ditelusuri kalau perlu
  di-revert sebagian.
- Kalau di tengah jalan ternyata instruksi di file `.md` **tidak cocok**
  dengan kondisi kode yang sebenarnya (misal nama fungsi/file yang
  disebut ternyata sudah beda), **jangan dipaksakan** — laporkan
  ketidaksesuaiannya, tunggu arahan, jangan improvisasi sendiri
  menebak-nebak maksudnya.
