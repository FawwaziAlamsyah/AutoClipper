```
Ubah fitur watermark di AutoClipper supaya posisi & ukurannya bisa diatur
lewat drag di atas preview video, mirip CapCut, menggantikan dropdown
preset posisi yang sekarang ada. TIDAK menambah dependency baru (JS
vanilla saja, tanpa library drag-and-drop eksternal). TIDAK mengubah cara
kerja render FFmpeg (tetap 1x render saat user klik Apply, drag itu sendiri
murni visual di browser, tidak memanggil FFmpeg).

1. app/services/clip_editor_service.py — method add_watermark()
   - Tambahkan parameter baru (opsional):
       x_pct: float | None = None,   # 0.0–1.0, posisi kiri watermark relatif ke lebar video
       y_pct: float | None = None,   # 0.0–1.0, posisi atas watermark relatif ke tinggi video
   - Kalau x_pct dan y_pct diisi (bukan None):
       - Validasi masing-masing harus 0.0 <= value <= 1.0, kalau tidak
         raise ValidationException("x_pct/y_pct harus antara 0.0–1.0").
       - x_expr = f"(main_w-overlay_w)*{x_pct}"
       - y_expr = f"(main_h-overlay_h)*{y_pct}"
       - Abaikan `position_map` & `margin_px` sepenuhnya di jalur ini.
   - Kalau x_pct/y_pct None (backward compat), pakai logic position_map
     yang sudah ada sekarang (tidak berubah).
   - Setelah render sukses (temp_path di-rename ke output_path), simpan
     posisi/ukuran/opacity TERAKHIR yang dipakai ke file JSON
     `settings.WATERMARK_PATH.parent / "watermark_position.json"`, isi:
       {"x_pct": ..., "y_pct": ..., "scale": ..., "opacity": ...}
     (skip penulisan file ini kalau x_pct/y_pct None / dipanggil lewat
     preset lama). Tulis dengan try/except supaya kegagalan simpan
     preferensi TIDAK menggagalkan proses watermark utama.
   - Tambahkan method baru:
       def get_last_watermark_position(self) -> dict:
           """Baca posisi/ukuran watermark terakhir dari
           watermark_position.json. Return default (x_pct=0.65, y_pct=0.80,
           scale=0.30, opacity=0.8) kalau file belum ada / corrupt."""
   - Update log info di akhir add_watermark() supaya ikut mencatat
     x_pct/y_pct kalau dipakai.

2. app/routers/clip_router.py
   - Endpoint POST /{clip_id}/edit/watermark: tambahkan Form fields baru
       x_pct: float | None = Form(None),
       y_pct: float | None = Form(None),
     lalu teruskan ke service.add_watermark(clip_id, position, scale,
     opacity, x_pct=x_pct, y_pct=y_pct). `position` tetap ada di form
     sebagai fallback backward-compat, tapi frontend baru tidak akan
     mengirim dropdown position lagi (lihat langkah 3).
   - Tambahkan endpoint baru:
       @router.get("/watermark/last-position", response_class=JSONResponse)
       def get_last_watermark_position(
           service: ClipEditorService = Depends(get_clip_editor_service),
       ) -> dict:
           """Posisi/ukuran/opacity watermark terakhir dipakai, untuk
           inisialisasi drag handle saat tab watermark dibuka."""
           return service.get_last_watermark_position()

3. app/templates/candidate_detail_content.html — tab Watermark
   a. Bungkus <video> yang sudah ada di _clip_edit_preview.html (atau
      wrapper baru khusus tab watermark) dengan container relative:
        <div id="wm-drag-stage" style="position:relative; display:inline-block;">
          <!-- video existing di sini, TIDAK diduplikasi/re-render -->
          <img id="wm-drag-handle" src="/data/assets/watermark.png?v={{ ts|default(0) }}"
               style="position:absolute; cursor:move; touch-action:none;">
          <div id="wm-resize-handle"
               style="position:absolute; width:14px; height:14px; border-radius:50%;
                      background:#fff; border:2px solid #0d6efd; cursor:nwse-resize;"></div>
        </div>
      Drag handle (#wm-drag-handle) dan resize handle
      (#wm-resize-handle, diposisikan di pojok kanan-bawah watermark)
      harus punya pointer-events aktif dan z-index di atas <video>, supaya
      drag tidak memicu kontrol play/pause di video di baliknya.
   b. Hapus <select name="position">...</select> yang lama. Ganti dengan
      hidden input yang di-update JS:
        <input type="hidden" name="x_pct" id="wm-x-pct">
        <input type="hidden" name="y_pct" id="wm-y-pct">
      Slider scale & opacity yang sudah ada TETAP dipertahankan sebagai
      input `scale`/`opacity` di form yang sama — resize via drag HARUS
      mengupdate value slider ini juga (dan sebaliknya, slider mengupdate
      ukuran #wm-drag-handle), supaya kedua kontrol selalu sinkron.
   c. Saat tab watermark pertama kali dibuka (atau saat halaman load),
      fetch GET /clips/watermark/last-position, lalu inisialisasi posisi
      #wm-drag-handle, value slider scale/opacity, dan hidden input
      x_pct/y_pct dari hasil fetch tersebut (bukan hardcoded default),
      supaya user langsung lihat posisi terakhir yang pernah dipakai.
   d. JS drag handler (vanilla, Pointer Events API supaya jalan di mouse
      & touch):
        - pointerdown di #wm-drag-handle → mode "move": simpan offset
          awal kursor terhadap handle.
        - pointerdown di #wm-resize-handle → mode "resize": simpan lebar
          awal watermark.
        - pointermove di document:
            - mode "move": update posisi #wm-drag-handle (CSS left/top),
              CLAMP supaya watermark tidak keluar batas stage.
            - mode "resize": update lebar #wm-drag-handle proporsional
              terhadap jarak drag, CLAMP ke rentang scale yang sama
              dengan slider (5%–50% dari lebar video), lalu sync value
              slider `scale` secara live.
        - pointerup → selesai drag/resize. Hitung x_pct/y_pct FINAL
          relatif ke UKURAN VIDEO ASLI (bukan ukuran elemen di layar):
          kalau <video> pakai object-fit:contain dan ada letterbox,
          hitung dulu area video efektif pakai videoWidth/videoHeight vs
          clientWidth/clientHeight sebelum konversi ke persen supaya
          akurat. Update value #wm-x-pct dan #wm-y-pct.
   e. Form submit tab watermark tetap pakai submitEditForm() yang sudah
      ada (tidak perlu fungsi baru) — otomatis ikut kirim x_pct/y_pct
      karena sudah jadi hidden input di dalam <form> yang sama.

4. i18n (app/core/translate.py)
   - Hapus key yang cuma dipakai dropdown preset lama KALAU tidak dipakai
     di tempat lain — cek dulu dengan:
       grep -rn "candDetail.watermarkTop\|candDetail.watermarkBottom\|candDetail.center" app
     JANGAN hapus candDetail.top/middle/bottom/center kalau ternyata masih
     dipakai di tab Text (posisi text overlay pakai key yang mirip tapi
     terpisah).
   - Tambahkan key baru untuk instruksi UI, en + id, contoh:
       "candDetail.watermarkDragHint":
         en: "Drag the logo to position it, drag the corner dot to resize"
         id: "Geser logo untuk atur posisi, geser titik pojok untuk ubah ukuran"

5. Test
   - tests/unit/test_clip.py:
     a. add_watermark() dengan x_pct/y_pct terisi → filter_complex yang
        dibentuk memakai ekspresi (main_w-overlay_w)*x_pct, bukan
        position_map.
     b. Validasi: x_pct=1.5 atau y_pct=-0.1 harus raise ValidationException.
     c. Backward-compat: panggil add_watermark() TANPA x_pct/y_pct →
        behavior identik seperti sebelum perubahan ini.
     d. add_watermark() dengan x_pct/y_pct terisi harus menulis
        watermark_position.json dengan isi yang sesuai; panggilan tanpa
        x_pct/y_pct tidak menulis/mengubah file tsb.
     e. get_last_watermark_position() mengembalikan default yang benar
        kalau file belum ada, dan mengembalikan isi file yang benar kalau
        file ada.

Batasan / hal yang TIDAK boleh diubah:
- Watermark tetap 1 file global (data/assets/watermark.png) untuk semua
  clip — jangan diubah jadi per-clip di prompt ini.
- Endpoint upload watermark (/clips/watermark/upload) tidak berubah.
- Jangan tambah library JS pihak ketiga (interact.js, dnd-kit, dsb) —
  pointer events vanilla sudah cukup dan menjaga project tetap ringan
  tanpa build step.
- Proses render FFmpeg tetap satu kali per klik "Apply" — jangan ada
  pemanggilan FFmpeg saat drag/resize berlangsung.
- Penyimpanan "posisi terakhir" pakai file JSON sederhana di folder
  data/assets/, BUKAN tabel/migration DB baru — jaga perubahan tetap
  ringan sesuai pola project (watermark memang sudah file-based, bukan
  DB-based).
```
