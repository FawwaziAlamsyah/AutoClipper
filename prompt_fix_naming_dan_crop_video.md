# Prompt: Rapikan Naming "Crop" (Trim) + Fitur Crop Layout Video Beneran

Gunakan prompt ini di Claude Code (root project AutoClipper). Task terpisah dari 2 prompt sebelumnya (fix performa & update tombol generate) — tidak overlap file kalau dikerjakan berurutan, tapi tetap kerjakan **setelah** prompt "Update Tombol Generate Clip" karena keduanya sama-sama menyentuh `candidate_detail_content.html`.

---

## Konteks

Di tab edit clip (section "Edit Video" di halaman detail candidate), ada tab bernama **"Crop"** yang isinya sebenarnya adalah **trim berdasarkan waktu** (start detik – end detik, memotong durasi clip), BUKAN crop dalam artian memotong area/frame visual video. Ini membingungkan karena istilah "crop" di dunia editing video biasanya berarti memotong bagian gambar (kiri/kanan/atas/bawah), bukan memotong durasi.

File terkait:
- `app/templates/candidate_detail_content.html` — tab UI, sekitar baris 101 (nav tab) dan baris 132-147 (isi tab).
- `app/core/translate.py` — key `candDetail.crop` (baris ~132, value "Crop"), `candDetail.trimDesc` (baris ~138, sudah benar bilang "Trim video berdasarkan waktu"), `candDetail.startSec`, `candDetail.endSec`, `candDetail.applyTrim` (sudah benar "Terapkan Trim").
- `app/services/clip_editor_service.py::crop()` — method backend yang sebenarnya melakukan trim waktu (pakai `-ss`/`-t` ffmpeg, bukan filter `crop=`).
- `app/routers/clip_router.py` — route `POST /clips/{clip_id}/edit/crop`.

## Task 1 — Rapikan naming tab lama jadi "Trim" (UI-facing saja, low-risk)

1. Di `app/core/translate.py`, ubah value key `candDetail.crop` dari `"Crop"` menjadi `"Trim"` (atau `"Potong Durasi"` kalau mau lebih deskriptif dalam Bahasa Indonesia — pilih salah satu, konsisten dengan gaya penamaan tab lain di app ini seperti "Text", "Sound").
2. Deskripsi (`candDetail.trimDesc`) dan label tombol (`candDetail.applyTrim`) sudah benar menyebut "Trim", tidak perlu diubah.
3. **Jangan ubah** nama method `ClipEditorService.crop()` atau route `/clips/{clip_id}/edit/crop` di backend — itu di luar scope "naming di UI" yang diminta, dan mengubahnya berisiko break existing test/integrasi tanpa manfaat langsung ke user. Cukup ubah teks yang tampil ke user saja.
4. Setelah task 2 selesai (lihat di bawah), pastikan tab baru "Crop" (spatial, yang benar-benar crop) dan tab lama yang sudah di-rename jadi "Trim" **tidak bentrok penamaan** — user harus bisa langsung bedakan dari nama tab: "Trim" = potong durasi, "Crop" = potong area/frame video.

## Task 2 — Fitur Crop layout video yang sebenarnya (potong area frame)

### Rekomendasi pendekatan

Saya sarankan **Opsi 1 yang disederhanakan**: crop box interaktif (drag & resize) di atas preview thumbnail — bukan Opsi 2 (input angka X/Y polos). Alasannya: Opsi 2 tetap butuh visual "penggaris" supaya angkanya bermakna buat user (sesuai yang Anda minta), dan begitu ada visual guide di layar, effort untuk menambahkan drag-handle interaktif di atasnya itu **tidak jauh lebih besar** — tapi hasil akhirnya jauh lebih intuitif ("kaya edit foto di HP", sesuai permintaan awal Anda). Jadi kita dapat pengalaman drag-crop yang diinginkan TANPA effort tambahan besar dibanding bikin ruler statis.

Kalau nanti ternyata drag-interaktifnya kerasa berat untuk diimplementasi dengan stabil (banyak edge-case mouse/touch event), baru turunkan ke fallback murni Opsi 2 (lihat bagian "Fallback" di bawah).

### Spesifikasi fitur

**Tab baru "Crop" (terpisah dari tab "Trim")** di section Edit Video, dengan isi:

1. **Preview thumbnail statis** (bukan `<video>` player) — ambil 1 frame dari clip (misal di detik pertama atau tengah clip) sebagai gambar dasar untuk area crop. Ini lebih ringan & stabil dibanding overlay di atas elemen `<video>` yang sedang playback.
   - Tambahkan method baru di `app/services/ffmpeg_service.py`, misal `extract_thumbnail(video_path: str, timestamp: float, output_path: str) -> str`, pakai ffmpeg `-ss {timestamp} -i {video_path} -frames:v 1 {output_path}` (pola mirip `extract_preview_clip` yang sudah ada, tinggal disesuaikan untuk single-frame JPEG/PNG).
   - Buat endpoint baru `GET /clips/{clip_id}/thumbnail` yang generate & serve thumbnail ini (cache ke disk supaya tidak generate ulang tiap request, mirip pola cache lain di app).

2. **Crop box overlay** (div dengan border + 4-8 resize handle di sudut/tepi) digambar di atas `<img>` thumbnail tsb, pakai plain JS (mousedown/mousemove/mouseup + touchstart/touchmove/touchend supaya jalan juga di HP) — TIDAK perlu library eksternal, cukup vanilla JS, konsisten dengan pola app ini yang sudah pakai vanilla JS + htmx (cek `app/static/js/` kalau ada helper existing yang bisa direuse, kalau tidak ada buat baru).
   - User bisa **drag untuk pindah posisi** box dan **drag handle di tepi/sudut untuk resize**.
   - Simpan posisi/ukuran box dalam **persentase relatif terhadap thumbnail** (bukan pixel absolut), supaya gampang dikonversi ke resolusi asli video berapa pun ukurannya.

3. **Ruler/penggaris** di atas dan di kiri thumbnail (sesuai request Anda) — garis skala dengan angka persentase (0%, 25%, 50%, 75%, 100%) di tepi atas (mewakili sumbu X) dan tepi kiri (mewakili sumbu Y), supaya user selalu punya referensi visual walau lagi drag box.

4. **Readout angka real-time** di bawah/samping preview, update otomatis saat drag: tampilkan `X`, `Y`, `Width`, `Height` (dalam persen ATAU pixel video asli — pilih pixel video asli supaya user langsung tahu ukuran final, lebih intuitif), dengan **note penjelasan singkat**:
   - `X` = jarak dari **tepi kiri** video ke titik awal area crop.
   - `Y` = jarak dari **tepi atas** video ke titik awal area crop.
   - `Width`/`Height` = ukuran area crop yang akan diambil, dihitung dari titik (X, Y) tsb.
   - Tampilkan note ini sebagai teks kecil `text-muted` di bawah form, contoh: *"X = jarak dari kiri, Y = jarak dari atas. Area yang di-crop dimulai dari titik ini."*

5. **Preset rasio umum** (opsional tapi sangat membantu UX, sarankan ditambahkan): tombol cepat "9:16 (TikTok/Reels)", "1:1 (Square)", "Bebas" — saat dipilih, crop box otomatis menyesuaikan rasio tsb dan user tinggal geser posisi/besar-kecilnya saja, tidak perlu hitung manual.

6. **Tombol "Terapkan Crop"** — submit `X, Y, Width, Height` (dalam pixel, dikonversi dari persen box × resolusi asli video sebelum dikirim) ke endpoint baru.

### Perubahan backend

1. Tambah method baru di `app/services/clip_editor_service.py`, JANGAN pakai nama `crop()` lagi untuk hindari bentrok makna dengan method trim lama (yang tetap dipakai tab "Trim"). Sarankan nama `crop_frame(clip_id: int, x: int, y: int, width: int, height: int)`, isi logic:
   ```python
   cmd = [
       self.ffmpeg.ffmpeg_path, "-y",
       "-i", str(source),
       "-vf", f"crop={width}:{height}:{x}:{y}",
       "-c:v", "libx264", "-crf", "18", "-preset", "fast",
       "-c:a", "copy",
       "-movflags", "+faststart",
       str(temp_path),
   ]
   ```
   Validasi: `x >= 0`, `y >= 0`, `width > 0`, `height > 0`, dan `x + width <= video_width`, `y + height <= video_height` (ambil `video_width`/`video_height` dari `FFmpegService.extract_metadata()` yang sudah ada) — kalau tidak valid, raise `ValidationException` dengan pesan jelas.
2. Tambah route baru `POST /clips/{clip_id}/edit/crop-frame` di `app/routers/clip_router.py`, ikuti pola route edit lain yang sudah ada (`edit/text`, `edit/volume`) supaya konsisten (response HTML fragment yang sama, update `clip.edited_file_path`, dst).
3. Tambah key translation baru di `app/core/translate.py` untuk label tab crop baru, placeholder input, note penjelasan X/Y, dan tombol preset rasio.

### Fallback (kalau drag-interaktif dianggap terlalu ribet untuk diimplementasi)

Turunkan ke Opsi 2 murni: hilangkan drag-handle, ganti dengan 4 input angka manual (`X`, `Y`, `Width`, `Height`) di form biasa (mirip tab Trim yang sudah ada), TAPI tetap tampilkan:
- Thumbnail preview statis + ruler di atas/kiri (poin 1 & 3 tetap dikerjakan, cuma bagian drag box-nya yang dihilangkan).
- Kotak crop digambar **read-only** (update otomatis tiap user ubah angka di input, pakai `oninput` biasa, tanpa perlu drag) di atas thumbnail, supaya user tetap dapat feedback visual "kalau X saya isi segini, potongnya sampai mana" tanpa perlu interaksi drag yang kompleks.
- Ini tetap memenuhi permintaan inti Anda (ada penggaris + tahu efek angkanya) dengan effort implementasi jauh lebih kecil dibanding drag-resize penuh.

## Kriteria selesai / cara verifikasi

- Tab lama yang isinya trim waktu sekarang berlabel **"Trim"**, bukan "Crop" lagi.
- Ada tab baru **"Crop"** yang benar-benar memotong area visual frame video (hasil clip setelah crop resolusinya berubah sesuai `width`/`height` yang dipilih, bisa dicek pakai `ffprobe` terhadap `clip.edited_file_path`).
- Preview thumbnail + ruler + (drag box atau readonly box, sesuai opsi yang dipilih) berfungsi dan angkanya konsisten — kalau user pilih X=10% dari lebar video 1920px, badge/readout harus tunjukkan ±192px, dan hasil crop asli file-nya juga mulai dari situ (validasi manual dengan buka hasil crop-nya).
- Validasi backend menolak input yang bikin area crop keluar dari batas video (`x+width > video_width` dst) dengan pesan error yang jelas, bukan crash/500.
- Tidak merusak tab "Trim" yang lama — masih berfungsi seperti sebelumnya, cuma namanya berubah.
- Test terkait clip editor (`grep -rln "ClipEditorService\|edit/crop" tests/`) di-update/ditambah untuk cover method `crop_frame` baru.
