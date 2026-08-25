# TikTok 05 — UI: Connect Akun & Tombol Upload Draft

Bagian 5 dari 5 (seri TikTok selesai di sini). **Prasyarat: `tiktok01.md`-
`tiktok04.md` sudah selesai dan sudah terverifikasi end-to-end.**

## Task — Badge "Connect TikTok" di Upload Page

Di `app/templates/upload_content.html`, tambahkan di bagian atas (dekat
header halaman):

```html
<div id="tiktok-connect-status" class="mb-3">
  <!-- diisi JS saat load -->
</div>

<script>
async function checkTikTokConnection() {
  // Cukup cek lewat endpoint kecil — reuse GET /categories pattern, buat
  // endpoint serupa GET /tiktok/status yang return {"connected": bool, "open_id": str|null}
  const res = await fetch('/tiktok/status');
  const data = await res.json();
  const el = document.getElementById('tiktok-connect-status');
  if (data.connected) {
    el.innerHTML = `<span class="badge bg-success">✓ TikTok terhubung</span>`;
  } else {
    el.innerHTML = `<a href="/tiktok/oauth/login" class="btn btn-sm btn-dark">🔗 Connect Akun TikTok</a>`;
  }
}
checkTikTokConnection();
</script>
```

Tambahkan endpoint kecil ini di `tiktok_router.py`:

```python
@router.get("/status")
def tiktok_connection_status(
    repo: TikTokAccountRepository = Depends(get_tiktok_account_repo),
) -> dict:
    account = repo.get_first()
    return {"connected": account is not None, "open_id": account.open_id if account else None}
```

(Tambahkan `get_tiktok_account_repo` di `dependencies.py` kalau belum ada.)

## Task — Tombol "Upload ke TikTok (Draft)" di Clip Detail

Di `app/templates/candidate_detail_content.html`, tambahkan di dekat
tombol Generate Clip yang sudah ada (cuma muncul kalau `clip` sudah ada):

```html
{% if clip %}
<button class="btn btn-dark mt-2" id="tiktokPublishBtn" onclick="publishToTikTok({{ clip.id }})">
  📤 Upload ke TikTok (Draft/Private)
</button>
<div id="tiktok-publish-status" class="mt-2"></div>
{% endif %}
```

## Task — JS Publish + Polling

```html
<script>
async function publishToTikTok(clipId) {
  const btn = document.getElementById('tiktokPublishBtn');
  const statusEl = document.getElementById('tiktok-publish-status');
  btn.disabled = true;
  statusEl.innerHTML = '<span class="text-muted">Memulai upload...</span>';

  const res = await fetch(`/tiktok/publish/${clipId}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json();
    statusEl.innerHTML = `<span class="text-danger">Gagal: ${err.detail || 'unknown error'}</span>`;
    btn.disabled = false;
    return;
  }
  const { local_id } = await res.json();
  pollTikTokStatus(local_id, btn, statusEl);
}

async function pollTikTokStatus(localId, btn, statusEl) {
  const res = await fetch(`/tiktok/publish/${localId}/status`);
  const data = await res.json();

  if (data.status === 'complete') {
    statusEl.innerHTML = '<span class="text-success">✓ Berhasil! Cek app TikTok Anda (draft/private), tap Post kalau sudah oke.</span>';
    btn.disabled = false;
    return;
  }
  if (data.status === 'error' || data.status === 'timeout') {
    statusEl.innerHTML = `<span class="text-danger">Gagal: ${data.error || 'timeout, cek manual di TikTok Studio'}</span>`;
    btn.disabled = false;
    return;
  }

  statusEl.innerHTML = `<span class="text-muted">Status: ${data.status}...</span>`;
  setTimeout(() => pollTikTokStatus(localId, btn, statusEl), 2000);
}
</script>
```

## Definisi Selesai (Seri TikTok Selesai Total di Sini)

- Buka halaman Upload TANPA akun TikTok connect → muncul tombol "🔗
  Connect Akun TikTok".
- Klik, login+izinkan di TikTok → balik ke Upload, badge berubah jadi "✓
  TikTok terhubung".
- Buka Detail candidate yang clip-nya sudah di-generate → tombol "📤
  Upload ke TikTok" muncul.
- Klik tombol itu → status berubah `uploading` → `processing` →
  `complete`, tombol ke-disable selama proses, aktif lagi setelah selesai.
- Cek app TikTok di HP → video ada di draft/inbox, private, siap di-tap
  Post manual.
- Coba lagi tanpa akun TikTok connect (hapus row `tiktok_accounts` manual
  buat simulasi) → dapat pesan error jelas "Belum ada akun TikTok yang
  terhubung...", bukan crash.
- `pytest` tetap lulus.

Seluruh seri (Editor 4 file + TikTok Setup + TikTok 5 file kode = 10 file)
selesai di sini. Kalau nanti mau lanjut ke audit publik penuh (bukan
draft/private lagi), kabari saya — saya bantu susun dokumen yang
dibutuhkan TikTok (privacy policy, deskripsi use-case) sebagai seri
terpisah.
