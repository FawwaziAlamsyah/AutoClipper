# Category Training 06 — Upload UI: Dropdown Kategori Dinamis

Bagian 6 dari 14. **Prasyarat: file 01-05 sudah selesai** (endpoint
`GET /categories` harus sudah bisa dipanggil, dan `process_schema.py` sudah
punya `category_id`).

## Task — Hapus Field "Content Type"

Di `app/templates/upload_content.html`, **hapus total** blok
`<div class="col-md-3"><label>Content Type</label>...</div>` (cari lewat
`grep -n "Content Type" app/templates/upload_content.html` untuk baris
persisnya).

## Task — Ganti "Clip Style" Jadi Dropdown Dinamis

Ganti dropdown `clip_style` yang sekarang isinya hardcoded
(`viral/educational/funny/...`) jadi:

```html
<div class="col-md-3">
  <label class="form-label">Clip Style (Kategori)</label>
  <select class="form-select" id="pl-category-id">
    <option value="">Default (belum pilih kategori)</option>
    <!-- diisi JS -->
  </select>
</div>
```

## Task — JS Load Kategori dari API

```html
<script>
async function loadCategoryOptions() {
  const res = await fetch('/categories');
  const categories = await res.json();
  const select = document.getElementById('pl-category-id');
  categories.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = c.name;
    select.appendChild(opt);
  });
}
loadCategoryOptions();
</script>
```

## Task — Update Payload Pipeline Settings

Cari JS yang kumpulin payload sebelum kirim ke `/videos/{id}/process` (cari
`content_type:` dan `clip_style:` di file yang sama untuk baris persisnya):

```javascript
// HAPUS baris: content_type: document.getElementById('pl-content-type').value,
// GANTI baris clip_style jadi:
category_id: document.getElementById('pl-category-id').value || null,
```

## Definisi Selesai

- Buka halaman Upload → tidak ada lagi field "Content Type" sama sekali.
- Dropdown "Clip Style" isinya kosong dulu (belum ada kategori dibuat) —
  cuma ada opsi "Default (belum pilih kategori)", itu wajar untuk sekarang.
- Buat 1 kategori test lewat `POST /categories?name=Test` (dari file 04),
  refresh halaman Upload → kategori itu muncul di dropdown.
- Pilih kategori itu, submit form upload+process → cek Network tab browser,
  payload yang dikirim ada `category_id` dengan nilai ID yang benar, TIDAK
  ada lagi `content_type` di payload.
- **Jangan lanjut ke file 07** sebelum poin di atas terverifikasi.
