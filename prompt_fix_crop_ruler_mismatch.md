# Prompt: Fix Mismatch Ruler/Crop Box dengan Preview Asli di Tab Crop

Gunakan prompt ini di Claude Code (root project AutoClipper). Task kecil, 1 file (`app/templates/candidate_detail_content.html`), terpisah dari prompt-prompt sebelumnya.

---

## Bug yang dilaporkan

Di tab "Crop" halaman detail candidate, kotak crop yang digambar user tidak match dengan hasil crop video asli — posisi Y di preview lebih jauh ke bawah dari posisi Y sebenarnya di video, ada area kosong yang ikut terpotong. Screenshot menunjukkan ada blok abu-abu bertuliskan "Memuat preview..." yang **tetap kelihatan** di atas gambar thumbnail asli, keduanya numpuk vertikal (bukan satu nutupin yang lain).

## Root cause (sudah dikonfirmasi dari source code)

Di `candidate_detail_content.html`, sekitar baris 191-216:

```html
<div id="crop-thumb-wrapper" class="position-relative" ...>
  <div id="crop-thumb-loading" class="d-flex align-items-center justify-content-center bg-secondary text-white" style="width:400px;height:225px;">
    <span>{{ t("candDetail.cropFrameLoadingThumb") }}</span>
  </div>
  <img id="crop-thumb-img" src="" alt="thumbnail" style="display:none;max-width:100%;display:block;">
  <div id="crop-box" style="display:none;position:absolute;...">
    ...
  </div>
</div>
```

`#crop-thumb-loading` dan `#crop-thumb-img` itu **sibling block normal**, BUKAN saling menumpuk (tidak ada `position:absolute` di loading placeholder-nya, cuma `#crop-box` yang absolute). Alurnya bergantung 100% pada JS (`initCropTab()` di sekitar baris 888-922) yang toggle `loading.style.display = 'none'` begitu `img.onload` selesai. Kalau toggle ini gagal/telat karena:
- `img.src` sudah `complete` dari cache browser sehingga baris `if (img.src && img.complete && img.naturalWidth > 0) return;` bikin function keluar lebih awal tanpa sempat menjalankan hide-logic dengan benar di render berikutnya, ATAU
- konten tab ini di-render ulang lewat proses lain di halaman (htmx swap area lain) tanpa `initCropTab()` dipanggil ulang,

...maka `#crop-thumb-loading` (ukuran tetap 400x225) TETAP KELIHATAN, numpuk vertikal DI ATAS `#crop-thumb-img` yang sudah tampil di bawahnya. Karena `syncRulerSize()` (baris 924-935) dan `updateBoxFromPct()` (baris 944-955) menghitung ruler + posisi kotak crop berdasarkan `wrapper.offsetWidth/offsetHeight` (tinggi GABUNGAN placeholder+gambar saat itu terjadi), semua persentase Y yang digambar user ketarik ke bawah dari posisi sebenarnya di gambar asli — ini yang bikin hasil crop meleset.

## Fix yang harus dikerjakan

### 1. Ubah `#crop-thumb-loading` jadi overlay absolute, bukan sibling block

Ini fix PALING PENTING — membuat bug ini **tidak mungkin terjadi lagi secara struktural**, apa pun race condition JS-nya:

```html
<div id="crop-thumb-wrapper" class="position-relative" style="border:1px solid #dee2e6;overflow:hidden;cursor:crosshair;user-select:none;">
  <img id="crop-thumb-img" src="" alt="thumbnail" style="display:none;max-width:100%;width:100%;height:auto;">
  <div id="crop-thumb-loading" class="d-flex align-items-center justify-content-center bg-secondary text-white position-absolute top-0 start-0 w-100 h-100">
    <span>{{ t("candDetail.cropFrameLoadingThumb") }}</span>
  </div>
  <div id="crop-box" style="display:none;position:absolute;...">
    ...
  </div>
</div>
```

Perubahan:
- `#crop-thumb-loading` sekarang `position-absolute top-0 start-0 w-100 h-100` (Bootstrap utility classes) — MENUMPUK DI ATAS wrapper, bukan mendorong konten lain ke bawah. Hapus `width:400px;height:225px` inline style-nya — tidak perlu lagi karena sekarang ukurannya ikut wrapper (`w-100 h-100`), bukan ukuran tetap sendiri.
- `#crop-thumb-wrapper` perlu **tinggi awal yang wajar SEBELUM gambar ter-load** supaya placeholder tetap kelihatan proporsional (karena sekarang wrapper tingginya ikut konten — kalau img belum ada src/belum ke-render, wrapper bisa collapse jadi 0 tinggi). Tambahkan `min-height:225px` di `#crop-thumb-wrapper` sebagai fallback SEBELUM gambar load, yang otomatis diabaikan begitu gambar sudah render dengan tinggi aslinya (karena `min-height` cuma jadi batas bawah, bukan batas tetap).
- Urutan elemen sengaja saya taruh `img` SEBELUM `loading` div supaya kalau suatu saat toggle display gagal lagi, minimal secara visual placeholder yang nutupin (bukan mendorong ke bawah) — tapi tetap pastikan `loading.style.display='none'` di JS tetap jalan normal supaya placeholder-nya beneran hilang saat gambar siap, bukan cuma dianggap "aman karena ke-cover".

### 2. Perbaiki guard early-return di `initCropTab()` supaya tidak skip hide-logic

File yang sama, fungsi `initCropTab()` sekitar baris 888-922. Baris ini:

```js
if (img.src && img.complete && img.naturalWidth > 0) return; // sudah ter-load
```

Masalahnya: kalau kondisi ini TRUE (gambar sudah pernah load sebelumnya, misal user gonta-ganti tab), function langsung `return` TANPA memastikan `loading` div dalam keadaan tersembunyi dan TANPA re-sync ruler/crop box (padahal ukuran wrapper bisa saja berubah kalau container di-resize, atau kalau ini load pertama kali setelah tab pane baru saja jadi visible sehingga `offsetWidth/offsetHeight` sebelumnya sempat kebaca 0).

Ganti jadi:

```js
if (img.src && img.complete && img.naturalWidth > 0) {
  // Sudah pernah ter-load — pastikan tetap dalam state benar (loading
  // ketutup, ruler & crop box ter-sync ke ukuran wrapper SEKARANG, bukan
  // asumsi state lama masih valid — penting terutama saat tab baru saja
  // jadi visible, karena offsetWidth/offsetHeight bisa 0 kalau diukur
  // sewaktu elemen masih display:none).
  if (loading) loading.style.display = 'none';
  img.style.display = 'block';
  syncRulerSize();
  showCropBox();
  return;
}
```

### 3. Pastikan `syncRulerSize()` dipanggil ulang setelah tab benar-benar visible

Karena Bootstrap tab pane transisinya bisa async (fade), ada kemungkinan `initCropTab()` terpanggil (lewat `onclick` di tab button) SEBELUM tab pane-nya benar-benar `display:block`/visible, sehingga `wrapper.offsetWidth/offsetHeight` yang dibaca saat itu bernilai 0 atau salah. Tambahkan sedikit delay setelah `img.onload` sebelum sync pertama kali, ATAU (lebih robust) dengarkan event `shown.bs.tab` Bootstrap alih-alih murni `onclick`:

```js
document.querySelectorAll('button[data-bs-toggle="tab"][data-bs-target="#tab-crop-frame"]').forEach(btn => {
  btn.addEventListener('shown.bs.tab', () => {
    // Tab BENAR-BENAR sudah visible di sini — aman untuk baca offsetWidth/offsetHeight.
    syncRulerSize();
    if (document.getElementById('crop-thumb-img').style.display === 'block') {
      showCropBox();
    }
  });
});
```

(Boleh dikombinasikan dengan `onclick="initCropTab(...)"` yang sudah ada di HTML — `onclick` untuk mulai proses load gambar dari awal, `shown.bs.tab` khusus untuk re-sync ukuran setelah tab pane pasti sudah punya dimensi nyata.)

### 4. (Robustness tambahan, opsional tapi disarankan) Ukur dari `img`, bukan `wrapper`

Di `syncRulerSize()` dan `updateBoxFromPct()`, pertimbangkan baca `img.getBoundingClientRect()` / `img.offsetWidth`/`img.offsetHeight` langsung alih-alih `wrapper.offsetWidth/offsetHeight` — supaya kalaupun nanti ada elemen lain ditambahkan ke dalam wrapper (notifikasi, badge, dll) yang mengubah ukuran wrapper, ukuran ruler/crop-box tetap dijamin match dengan gambar asli, bukan ikut kebawa elemen tambahan itu. Ini pencegahan supaya bug sejenis tidak muncul lagi di masa depan kalau ada perubahan UI lain di area ini.

## Kriteria selesai / cara verifikasi

- Buka tab Crop untuk candidate yang belum pernah dibuka sebelumnya (thumbnail belum ke-cache) — pastikan placeholder "Memuat preview..." hilang total begitu gambar muncul, tidak ada sisa area abu-abu di atas/bawah gambar.
- Buka tab lain, balik lagi ke tab Crop (thumbnail sudah ke-cache dari sebelumnya) — pastikan TIDAK muncul placeholder numpuk di atas gambar (ini skenario yang paling mungkin jadi penyebab bug di screenshot).
- Gambar kotak crop dari Y=10% sampai Y=90% secara visual di preview, klik Terapkan Crop, lalu buka hasil video crop-nya — pastikan area yang benar-benar terpotong match dengan apa yang digambar di preview (tidak ada offset ke bawah seperti sebelumnya).
- Test juga di ukuran window browser yang beda-beda (resize), pastikan ruler tetap sinkron dengan ukuran gambar yang sebenarnya dirender saat itu.
