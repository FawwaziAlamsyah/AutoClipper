# Category Training 16 — Manajemen Kategori di Training Dashboard (Terakhir)

Bagian 16 dari 16 — **file terakhir seri ini.** Prasyarat: file 01-15 sudah
selesai.

## Task — Panel Manajemen Kategori

Tambahkan di bagian PALING ATAS `app/templates/training_dashboard_content.html`,
sebelum panel stats yang sudah ada:

```html
<div class="card shadow-sm p-4 mb-4">
  <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
    <h5 class="mb-0">Kategori</h5>
    <div class="d-flex gap-2">
      <input type="text" class="form-control form-control-sm" id="newCategoryName" placeholder="Nama kategori baru...">
      <button class="btn btn-sm btn-primary" onclick="createCategory()">+ Tambah</button>
    </div>
  </div>

  <div class="d-flex gap-2 flex-wrap mb-3">
    {% for cat in categories %}
    <a href="/training/dashboard?category_id={{ cat.id }}"
       hx-get="/training/dashboard?category_id={{ cat.id }}"
       hx-target="#main-content" hx-push-url="true"
       class="btn btn-sm {{ 'btn-primary' if cat.id == selected_category_id else 'btn-outline-secondary' }}">
      {{ cat.name }}
    </a>
    {% endfor %}
  </div>

  {% if selected_category_id %}
  <div class="d-flex gap-2">
    <button class="btn btn-sm btn-outline-secondary" onclick="renameCategory({{ selected_category_id }})">✏️ Ubah Nama</button>
    <button class="btn btn-sm btn-outline-danger" onclick="deleteCategory({{ selected_category_id }})">🗑 Hapus Kategori Ini</button>
  </div>
  {% endif %}
</div>
```

## Task — JS Manajemen Kategori

```html
<script>
async function createCategory() {
  const input = document.getElementById('newCategoryName');
  const name = input.value.trim();
  if (!name) { alert('Nama kategori tidak boleh kosong.'); return; }
  const res = await fetch(`/categories?name=${encodeURIComponent(name)}`, { method: 'POST' });
  if (res.ok) {
    const data = await res.json();
    window.location.href = `/training/dashboard?category_id=${data.id}`;
  } else {
    const err = await res.json();
    alert(err.detail || 'Gagal membuat kategori.');
  }
}

async function renameCategory(categoryId) {
  const newName = prompt('Nama baru untuk kategori ini:');
  if (!newName) return;
  const res = await fetch(`/categories/${categoryId}?name=${encodeURIComponent(newName)}`, { method: 'PUT' });
  if (res.ok) location.reload();
  else alert('Gagal mengubah nama.');
}

async function deleteCategory(categoryId) {
  if (!confirm('Hapus kategori ini? Model terlatihnya ikut terhapus. Candidate yang sudah ditandai kategori ini TIDAK terhapus, cuma jadi tanpa kategori.')) return;
  const res = await fetch(`/categories/${categoryId}`, { method: 'DELETE' });
  if (res.ok) window.location.href = '/training/dashboard';
  else alert('Gagal menghapus kategori.');
}
</script>
```

## Task — Tombol "Train Model" dan "Aktifkan" Kirim `category_id`

Cari fungsi JS `trainModel()` yang sudah ada di
`training_dashboard_content.html`, update URL fetch-nya:

```javascript
async function trainModel(btn) {
  const categoryId = {{ selected_category_id or 'null' }};
  if (!categoryId) { alert('Pilih kategori dulu.'); return; }
  // ... sisa logic yang sudah ada TETAP SAMA, cuma ganti fetch URL:
  const res = await fetch(`/training/train?category_id=${categoryId}`, { method: 'POST' });
  // ...
}
```

Fungsi `activateRun()` yang sudah ada — tidak perlu kirim `category_id`
(run_id sudah cukup unik), tapi setelah berhasil, redirect/reload balik ke
`?category_id={{ selected_category_id }}` supaya user tidak kepental ke
kategori pertama setelah refresh.

## Definisi Selesai (Seri Category Training Selesai Total di Sini)

- Buka `/training/dashboard` dengan minimal 2 kategori dibuat → ada tombol
  pilihan kategori di atas, klik salah satu → stats/riwayat/tombol Train di
  bawahnya berubah sesuai kategori yang dipilih (bukan gabungan semua).
- Bikin kategori baru dari tombol "+ Tambah" → langsung pindah ke dashboard
  kategori itu (masih kosong, 0 data).
- Kumpulkan ≥20 data training untuk 1 kategori (lewat dropdown kategori di
  candidate grid dari file 12, ATAU bulk CSV import dari file 15) → tombol
  "Train Model" berhasil, muncul di riwayat.
- Latih 2 kategori berbeda (kalau data cukup) → riwayat training
  masing-masing terpisah, tombol "Aktifkan" di kategori A tidak
  mempengaruhi model kategori B sama sekali.
- Hapus kategori → model & foldernya hilang dari disk, tapi candidate yang
  pernah ditandai kategori itu MASIH ADA di database (cuma `category_id`
  jadi NULL).
- Proses video baru, pilih kategori yang SUDAH punya model terlatih →
  `score_breakdown._meta.scoring_method` = `"trained_model"` (bukan
  `"weighted_sum"` lagi) — bukti seluruh alur dari Upload sampai Training
  benar-benar tersambung end-to-end.
- `pytest` penuh tetap lulus di seluruh project.
