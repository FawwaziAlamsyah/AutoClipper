# Category Training 12 — Endpoint & UI Rating Baru (Dropdown Kategori)

Bagian 12 dari 14. **Prasyarat: file 01-11 sudah selesai.**

## Task — Endpoint Baru di `candidate_router.py`

```python
@router.post("/{candidate_id}/categorize", response_class=HTMLResponse)
def categorize_candidate(
    request: Request,
    candidate_id: int,
    category_id: int,
    service: CandidateService = Depends(get_candidate_service),
    category_service: CategoryService = Depends(get_category_service),
):
    """Tandai candidate sebagai contoh positif kategori tertentu."""
    candidate = service.categorize(candidate_id, category_id)
    categories = category_service.list_categories()
    return templates.TemplateResponse(
        request=request,
        name="_rating_control.html",
        context={"request": request, "candidate": candidate, "categories": categories},
    )


@router.post("/{candidate_id}/uncategorize", response_class=HTMLResponse)
def uncategorize_candidate(
    request: Request,
    candidate_id: int,
    service: CandidateService = Depends(get_candidate_service),
    category_service: CategoryService = Depends(get_category_service),
):
    candidate = service.uncategorize(candidate_id)
    categories = category_service.list_categories()
    return templates.TemplateResponse(
        request=request,
        name="_rating_control.html",
        context={"request": request, "candidate": candidate, "categories": categories},
    )
```

Cari endpoint `/like` dan `/unlike` yang sudah ada — **hapus keduanya
sepenuhnya**, digantikan 2 endpoint di atas.

Endpoint `/dislike` dan `/undislike` yang sudah ada **tetap dipakai apa
adanya** (service-nya sudah berubah perilaku di file 11), cuma ganti nama
template response-nya jadi `_rating_control.html` juga (samakan dengan di
atas, supaya satu partial dipakai konsisten untuk seluruh area rating).

## Task — Partial Baru `_rating_control.html`

Buat file baru `app/templates/_rating_control.html`:

```html
{% if candidate.label_source == "user_liked" %}
<span class="badge bg-success">✓ {{ candidate.category.name if candidate.category else 'Kategori' }}</span>
<button class="btn btn-sm btn-link p-0 text-muted"
        onclick="doRatingAction({{ candidate.id }}, '/candidates/{{ candidate.id }}/uncategorize', 'POST')">batalkan</button>
{% elif candidate.label_source == "user_disliked" %}
<span class="badge bg-danger">👎 Jelek</span>
<button class="btn btn-sm btn-link p-0 text-muted"
        onclick="doRatingAction({{ candidate.id }}, '/candidates/{{ candidate.id }}/undislike', 'POST')">batalkan</button>
{% else %}
<div class="d-flex gap-1 align-items-center flex-wrap">
  <select class="form-select form-select-sm" style="width:auto;" id="category-select-{{ candidate.id }}">
    <option value="">Tandai kategori...</option>
    {% for cat in categories %}
    <option value="{{ cat.id }}">{{ cat.name }}</option>
    {% endfor %}
  </select>
  <button type="button" class="btn btn-sm btn-outline-success"
          onclick="submitCategorize({{ candidate.id }})">✓</button>
  <button type="button" class="btn btn-sm btn-outline-danger"
          onclick="openDislikeModal({{ candidate.id }})">👎</button>
</div>
{% endif %}
```

## Task — JS Pendukung

Taruh di `candidates_video_content.html`, di luar loop (bareng modal
Dislike yang sudah ada dari sebelumnya — modal itu TETAP DIPAKAI apa
adanya, cuma modal/tombol Like yang dihapus):

```javascript
function submitCategorize(candidateId) {
  const select = document.getElementById('category-select-' + candidateId);
  const categoryId = select.value;
  if (!categoryId) {
    alert('Pilih kategori dulu.');
    return;
  }
  doRatingAction(candidateId, `/candidates/${candidateId}/categorize?category_id=${categoryId}`, 'POST');
}

async function doRatingAction(candidateId, url, method) {
  const res = await fetch(url, { method: method });
  if (res.ok) {
    const html = await res.text();
    document.getElementById('like-status-' + candidateId).innerHTML = html;
  } else {
    alert('Gagal. Coba lagi.');
  }
}
```

Kalau sebelumnya ada fungsi `doLikeAction` — hapus, digantikan
`doRatingAction` di atas. Cari semua pemanggil `doLikeAction` lain (kalau
ada) dan ganti ke `doRatingAction`.

## Task — Ganti Semua Referensi ke Partial Lama

Cari semua `{% include "_like_button_compact.html" %}` (ada di
`_candidate_row.html` dan kemungkinan file lain), ganti jadi:

```html
{% include "_rating_control.html" %}
```

Setelah dipastikan tidak ada referensi tersisa, hapus file
`_like_button_compact.html`.

## Definisi Selesai

- `grep -rn "_like_button_compact.html\|doLikeAction\|/candidates/.*\/like\b\|/candidates/.*\/unlike\b" app/`
  hasilnya kosong total.
- Buka grid candidate → tidak ada lagi tombol "Like" polos, diganti
  dropdown kategori + tombol centang + tombol Dislike (Dislike tetap sama
  seperti sebelumnya, dengan modal konfirmasi).
- Pilih kategori dari dropdown lalu klik centang → badge berubah jadi nama
  kategori yang dipilih.
- Klik "batalkan" di badge kategori → kembali ke tampilan dropdown.
- Klik Dislike (dengan konfirmasi) → badge "Jelek" muncul.
- `pytest` tetap lulus.
- **Jangan lanjut ke file 13** sebelum poin di atas terverifikasi.
