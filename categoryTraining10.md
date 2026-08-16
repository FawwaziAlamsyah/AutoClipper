# Category Training 10 — `CandidateService`: `categorize()` Menggantikan `mark_as_liked()`

Bagian 10 dari 14. **Prasyarat: file 01-09 sudah selesai.**

Konteks: mulai file ini, cara user memberi label berubah — tombol "Like"
generik dihapus, diganti pilih kategori langsung (assign candidate ini jadi
contoh POSITIF kategori X). File ini baru sisi service-nya dulu, UI-nya di
file 12.

## Task — Tambah `categorize()` dan `uncategorize()`

Di `app/services/candidate_service.py`:

```python
def categorize(self, candidate_id: int, category_id: int) -> CandidateModel:
    """Tandai candidate sebagai contoh POSITIF untuk kategori tertentu.

    Menggantikan mark_as_liked() lama — sekarang wajib pilih kategori,
    bukan cuma "like" generik.
    """
    candidate = self.candidate_repo.get(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    candidate.actual_score = settings.LIKED_CLIP_DEFAULT_SCORE
    candidate.is_training_example = True
    candidate.label_source = "user_liked"
    candidate.category_id = category_id
    self.db.commit()
    self.db.refresh(candidate)
    logger.info("Candidate %d ditandai contoh kategori %d", candidate_id, category_id)
    return candidate

def uncategorize(self, candidate_id: int) -> CandidateModel:
    """Batalkan penandaan kategori — kembalikan ke kondisi bukan training example."""
    candidate = self.candidate_repo.get(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    if candidate.label_source == "user_liked":
        candidate.actual_score = None
        candidate.is_training_example = False
        candidate.label_source = None
        candidate.category_id = None
        self.db.commit()
        self.db.refresh(candidate)
    return candidate
```

## Task — Hapus Method Lama

Hapus `mark_as_liked()` dan `unmark_liked()` sepenuhnya dari
`candidate_service.py` — digantikan `categorize()`/`uncategorize()` di
atas. **Jangan hapus dulu `mark_as_disliked()`/`unmark_disliked()`** — itu
bagian file 11, beda konsen.

## Definisi Selesai

- `python -m py_compile app/services/candidate_service.py` lulus.
- `grep -n "mark_as_liked\|unmark_liked" app/services/candidate_service.py`
  hasilnya kosong (sudah terhapus total).
- **Belum bisa ditest lewat endpoint** (routernya di file 12) — cukup
  pastikan tidak ada syntax error dan method baru ada.
- `pytest` tetap lulus (kalau ada test lama yang manggil `mark_as_liked`,
  laporkan dulu, jangan diam-diam dihapus/diubah sendiri).
- **Jangan lanjut ke file 11** sebelum poin di atas terverifikasi.
