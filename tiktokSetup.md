# TikTok Setup — Langkah Manual (Bukan Kode, Harus Anda Kerjakan Sendiri)

**Kerjakan file ini PALING PERTAMA, sebelum `tiktok01.md` dst.** Ini bukan
prompt buat AI coding — ini checklist manual yang cuma bisa Anda lakukan
sendiri (butuh akun TikTok Anda, tidak bisa diwakilkan).

## Kenapa Ini Perlu

API resmi TikTok (Content Posting API) butuh app terdaftar di TikTok for
Developers. Tanpa ini, tidak ada `client_key`/`client_secret` yang
dibutuhkan seri `tiktok01.md` dst.

## Langkah-Langkah

### 1. Daftar di TikTok for Developers

Buka [developers.tiktok.com](https://developers.tiktok.com), login pakai
akun TikTok Anda, buat aplikasi baru.

### 2. Tambahkan Product "Content Posting API"

Di dashboard app Anda, aktifkan product **Content Posting API** (bukan
Login Kit doang — harus eksplisit ditambahkan sebagai product terpisah).

### 3. Set Redirect URI

Karena AutoClipper jalan lokal, set redirect URI OAuth ke:

```
http://localhost:8000/tiktok/oauth/callback
```

(Sesuaikan port kalau server Anda jalan di port lain.) Kalau TikTok
menolak `localhost` sebagai redirect URI yang valid (beberapa provider
OAuth memang ketat soal ini), kemungkinan Anda perlu setup domain
sederhana (bisa domain gratis) yang mengarah ke tunnel lokal (ngrok, dsb)
— ini di luar kendali saya untuk pastikan dari sini, tergantung kebijakan
TikTok saat Anda daftar.

### 4. Catat `client_key` dan `client_secret`

Simpan baik-baik, akan dimasukkan ke `.env` di `tiktok01.md`.

### 5. Pahami Batasan Mode "Unaudited" (Ini yang Kita Pakai Sekarang)

- Semua post yang di-upload **otomatis private** (`SELF_ONLY`) — cuma Anda
  yang bisa lihat di app TikTok Anda sendiri, lalu tap "Post" manual dari
  situ kalau mau publish.
- Maksimal **5 user berbeda** bisa connect ke app ini dalam 24 jam — untuk
  pemakaian personal (cuma akun Anda sendiri), ini bukan masalah.
- **Tidak perlu audit** untuk mode ini — bisa langsung dipakai begitu app
  terdaftar dan langkah 1-4 selesai.

### 6. (Boleh Dilewati Dulu) Kalau Nanti Mau Auto-Publish Publik Penuh

Butuh audit manual TikTok — privacy policy URL asli, deskripsi use-case
spesifik, demo video/screenshot. Proses hari-minggu, di luar scope
teknis. Kabari saya kalau sudah siap ke tahap ini, saya bantu draft
dokumen yang dibutuhkan (privacy policy template, deskripsi use-case).

## Definisi Selesai

- Anda punya `client_key` dan `client_secret` dari dashboard TikTok for
  Developers.
- Content Posting API sudah aktif sebagai product di app Anda.
- Redirect URI sudah di-set (dan Anda tahu apakah `localhost` diterima
  atau perlu domain).
- **Jangan lanjut ke `tiktok01.md`** sebelum ketiga poin di atas beres.
