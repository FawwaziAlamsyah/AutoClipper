# UI Redesign 1 — Grid Candidate ala YouTube (Preview & Like/Dislike di Depan)

Konteks: sekarang `candidates_video_content.html` (daftar candidate per video)
berupa tabel, dan preview video + tombol Like/Dislike cuma ada di halaman
Detail. Pindahkan preview + Like/Dislike ke halaman depan (grid card, model
YouTube: thumbnail + durasi + judul + aksi), sisakan halaman Detail cuma untuk
Score Breakdown dan Subtitle (Generate Clip tetap di Detail — subtitle butuh
clip yang sudah di-generate dulu, jadi actionnya tetap satu paket).

Grid pakai Bootstrap `row-cols` responsive (3 kolom desktop, otomatis
menyesuaikan ke 2/1 kolom di layar sempit, dan otomatis wrap ke baris baru
sesuai jumlah candidate — tidak perlu logic manual untuk "banyak/sedikit
clip").

**Prasyarat: kerjakan `previewFix1.md` dulu kalau belum** — grid ini pakai
endpoint `/preview/candidates/{id}/clip` (server-trimmed preview) yang
dibangun di situ, bukan video mentah utuh.

---

## Task 1 — Ganti Isi `_candidate_row.html` Jadi Card Grid

**Nama file TETAP `_candidate_row.html`** (jangan rename) — supaya
`clip_router.py` (`generate-htmx` endpoint) dan JS (`generateClipRow`,
`deleteCandidate`) yang sudah mereferensikan nama ini tidak perlu diubah.
Cuma isinya yang berubah dari `<tr>` jadi card grid:

```html
<div class="col-md-6 col-lg-4" id="row-{{ candidate.id }}">
  <div class="card shadow-sm h-100">
    <div class="position-relative bg-dark rounded-top overflow-hidden" style="aspect-ratio:16/9;">
      <video class="w-100 h-100" style="object-fit:cover;" controls preload="metadata">
        <source src="/preview/candidates/{{ candidate.id }}/clip" type="video/mp4">
      </video>
      <span class="badge bg-dark position-absolute bottom-0 end-0 m-2">
        {% set dur = candidate.end_time - candidate.start_time %}
        {{ '%d:%02d'|format((dur // 60)|int, (dur % 60)|int) }}
      </span>
    </div>
    <div class="card-body pb-2">
      <h6 class="mb-1 text-truncate" title="{{ candidate.hook_text or ('Candidate #' ~ candidate.id) }}">
        {{ candidate.hook_text or ('Candidate #' ~ candidate.id) }}
      </h6>
      <p class="text-muted small mb-2">
        Score <strong>{{ candidate.final_score }}</strong> ·
        <span class="badge bg-{{ 'success' if candidate.clip_filename else ('warning text-dark' if candidate.status == 'selected' else 'secondary') }}">
          {{ 'clip ready' if candidate.clip_filename else candidate.status }}
        </span>
      </p>
      <div class="d-flex flex-wrap gap-1 mb-2" id="like-status-{{ candidate.id }}">
        {% include "_like_button_compact.html" %}
      </div>
    </div>
    <div class="card-footer bg-transparent border-top-0 pt-0 pb-3 px-3">
      <div class="d-flex flex-wrap gap-1">
        {% if candidate.clip_filename %}
        <a class="btn btn-sm btn-success" target="_blank" href="/data/outputs/{{ candidate.clip_filename }}">Open</a>
        {% else %}
        <button class="btn btn-sm btn-primary" onclick="generateClipRow(this, {{ candidate.id }})">Generate</button>
        {% endif %}
        <a class="btn btn-sm btn-outline-info"
           href="/candidates/{{ candidate.id }}"
           hx-get="/candidates/{{ candidate.id }}"
           hx-target="#main-content"
           hx-push-url="true">Detail</a>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteCandidate(this, {{ candidate.id }})">Hapus</button>
      </div>
    </div>
  </div>
</div>
```

Catatan: `id="row-{{ candidate.id }}"` dipertahankan persis (walau sekarang
elemennya `<div class="col...">` bukan `<tr>`) — JS `generateClipRow`/
`deleteCandidate` yang sudah ada manggil `document.getElementById('row-' +
candidateId)` dan `.outerHTML`/`.remove()`, itu tetap jalan tanpa ubah JS-nya
sama sekali selama id-nya konsisten.

## Task 2 — Bungkus Grid di `candidates_video_content.html`

Ganti `<table>` jadi grid wrapper:

```html
{% if candidates %}
<div class="row g-3">
  {% for candidate in candidates %}
  {% include "_candidate_row.html" %}
  {% endfor %}
</div>
{% else %}
<div class="card shadow-sm p-5 text-center text-muted">
  Belum ada candidates untuk video ini.
</div>
{% endif %}
```

## Task 3 — `_like_button_compact.html` (Baru) + Modal Konfirmasi Bersama

Karena sekarang BANYAK candidate tampil sekaligus di satu halaman (beda dari
Detail yang cuma 1 candidate), modal konfirmasi Like/Dislike **tidak boleh
diduplikasi per-card** (ID duplikat di DOM itu invalid HTML, dan Bootstrap
cuma akan buka modal pertama yang ketemu). Solusinya: **satu modal dipakai
bersama**, JS ingat candidate mana yang lagi diproses.

### `app/templates/_like_button_compact.html` (baru)

```html
{% if candidate.label_source == "user_liked" %}
<span class="badge bg-success">👍 Liked</span>
<button class="btn btn-sm btn-link p-0 text-muted"
        onclick="doLikeAction({{ candidate.id }}, '/candidates/{{ candidate.id }}/unlike')">batalkan</button>
{% elif candidate.label_source == "user_disliked" %}
<span class="badge bg-danger">👎 Jelek</span>
<button class="btn btn-sm btn-link p-0 text-muted"
        onclick="doLikeAction({{ candidate.id }}, '/candidates/{{ candidate.id }}/undislike')">batalkan</button>
{% else %}
<button type="button" class="btn btn-sm btn-outline-success" onclick="openLikeModal({{ candidate.id }})">👍 Like</button>
<button type="button" class="btn btn-sm btn-outline-danger" onclick="openDislikeModal({{ candidate.id }})">👎 Jelek</button>
{% endif %}
```

### Modal + JS bersama, taruh SEKALI di akhir `candidates_video_content.html` (di luar loop)

```html
<div class="modal fade" id="likeConfirmModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Konfirmasi Like</h5><button class="btn-close" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">Tandai clip ini sebagai contoh BAGUS untuk melatih sistem scoring?</div>
    <div class="modal-footer">
      <button class="btn btn-secondary" data-bs-dismiss="modal">Batal</button>
      <button class="btn btn-success" id="likeConfirmBtn">Ya, Like &amp; Latih</button>
    </div>
  </div></div>
</div>

<div class="modal fade" id="dislikeConfirmModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Konfirmasi Tandai Jelek</h5><button class="btn-close" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">Tandai clip ini sebagai contoh <strong>BURUK</strong> untuk melatih sistem scoring?</div>
    <div class="modal-footer">
      <button class="btn btn-secondary" data-bs-dismiss="modal">Batal</button>
      <button class="btn btn-danger" id="dislikeConfirmBtn">Ya, Tandai Jelek</button>
    </div>
  </div></div>
</div>

<script>
let pendingCandidateId = null;

function openLikeModal(candidateId) {
  pendingCandidateId = candidateId;
  new bootstrap.Modal(document.getElementById('likeConfirmModal')).show();
}
function openDislikeModal(candidateId) {
  pendingCandidateId = candidateId;
  new bootstrap.Modal(document.getElementById('dislikeConfirmModal')).show();
}

document.getElementById('likeConfirmBtn').addEventListener('click', async () => {
  bootstrap.Modal.getInstance(document.getElementById('likeConfirmModal'))?.hide();
  await doLikeAction(pendingCandidateId, `/candidates/${pendingCandidateId}/like`);
});
document.getElementById('dislikeConfirmBtn').addEventListener('click', async () => {
  bootstrap.Modal.getInstance(document.getElementById('dislikeConfirmModal'))?.hide();
  await doLikeAction(pendingCandidateId, `/candidates/${pendingCandidateId}/dislike`);
});

async function doLikeAction(candidateId, url) {
  const res = await fetch(url, { method: 'POST', headers: { 'HX-Request': 'true' } });
  if (res.ok) {
    const html = await res.text();
    document.getElementById('like-status-' + candidateId).innerHTML = html;
  } else {
    alert('Gagal. Coba lagi.');
  }
}
</script>
```

## Task 4 — Update Router: Endpoint Like/Unlike/Dislike/Undislike Render Partial Baru

Di `app/routers/candidate_router.py`, keempat endpoint ini (`like`, `unlike`,
`dislike`, `undislike`) sekarang render `_like_button.html` — ganti jadi
`_like_button_compact.html` di keempatnya:

```python
return templates.TemplateResponse(
    request=request,
    name="_like_button_compact.html",  # sebelumnya "_like_button.html"
    context={"request": request, "candidate": candidate},
)
```

## Task 5 — Bersihkan `candidate_detail_content.html`

Hapus dari file ini:
- Seluruh blok `<!-- Preview Video -->` (card kolom kanan berisi `<video>`)
  — ganti layout `row g-4` jadi 1 kolom penuh untuk Score Breakdown saja
  (`col-lg-6` → `col-12`, atau biarkan `col-lg-8 mx-auto` kalau mau tetap
  tidak terlalu lebar).
- Baris `<div class="d-flex ... id="like-status">{% include "_like_button.html" %}</div>`
  di section "Render Clip" — Like/Dislike sudah pindah ke grid depan, tidak
  perlu lagi di Detail.
- Modal `#likeConfirmModal` dan `#dislikeConfirmModal` beserta listener JS-nya
  (`likeConfirmBtn`/`dislikeConfirmBtn` click handler, fungsi `doLikeAction`)
  — semua urusan like/dislike sudah pindah ke `candidates_video_content.html`.
- Blok `<script>` `seekPreview()` — sudah tidak relevan, tidak ada lagi
  `<video id="candidateVideo">` di halaman ini.

**Yang TETAP ada di Detail** (sesuai instruksi Anda): Score Breakdown penuh,
tombol Generate Clip + hasilnya, dan section Subtitle (yang muncul setelah
clip ada). Generate Clip sengaja tidak dipindah karena Subtitle butuh clip
sudah di-generate dulu — satu alur yang sama.

## Task 6 — Hapus File Lama yang Sudah Tidak Terpakai

`app/templates/_like_button.html` (versi lama, full-size) sudah tidak
dipakai dari mana pun setelah Task 4-5 — hapus filenya.

---

## Definisi Selesai

- Buka `/candidates/video/{id}` → tampil grid card (bukan tabel), 3 kolom di
  layar desktop, otomatis jadi 2/1 kolom di layar sempit, jumlah baris grid
  menyesuaikan jumlah candidate otomatis (test dengan video yang punya
  banyak candidate DAN video yang cuma punya 1-2 candidate).
- Tiap card: video preview bisa diputar (durasi = durasi clip, bukan video
  penuh — hasil dari `previewFix1.md`), badge durasi muncul di pojok kanan
  bawah thumbnail, tombol Like/Dislike ada langsung di card.
- Klik Like di salah satu card → modal konfirmasi muncul, setelah konfirmasi
  cuma card itu yang berubah statusnya (badge "Liked"), card lain di grid
  TIDAK ikut berubah/reload.
- Coba Like di 2 card berbeda satu demi satu → masing-masing update ke
  candidate yang benar (bukti `pendingCandidateId` tracking bekerja, bukan
  salah update ke candidate lain).
- Buka Detail salah satu candidate → tidak ada lagi video preview atau
  tombol Like/Dislike di situ, cuma Score Breakdown, Generate Clip, dan
  Subtitle (kalau clip sudah ada).
- `grep -rn "_like_button.html" app/` cuma muncul kalau memang belum dihapus
  filenya — setelah Task 6, hasil grep harus kosong total.
