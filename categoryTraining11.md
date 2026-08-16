# Category Training 11 — Dislike Tidak Lagi Jadi Data Training

Bagian 11 dari 14. **Prasyarat: file 01-10 sudah selesai.**

Konteks: Dislike tetap ada sebagai tombol (UI-nya di file 12), tapi mulai
file ini, dislike **tidak lagi berkontribusi ke data training sama
sekali** — murni jadi penanda/hide clip jelek, fokus training murni dari
kategori positif yang di-assign lewat `categorize()` (file 10).

## Task — Ubah `mark_as_disliked()`

Di `app/services/candidate_service.py`:

```python
def mark_as_disliked(self, candidate_id: int) -> CandidateModel:
    """Tandai candidate sebagai clip JELEK — cuma penanda kualitas, TIDAK
    dipakai sebagai data training (beda dari desain lama). Cukup untuk
    menyembunyikan/menandai, fokus training murni dari kategori positif.
    """
    candidate = self.candidate_repo.get(candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    candidate.label_source = "user_disliked"
    # is_training_example & actual_score SENGAJA tidak diisi — dislike
    # tidak lagi berkontribusi ke data training sama sekali.
    self.db.commit()
    self.db.refresh(candidate)
    logger.info("Candidate %d ditandai jelek (bukan data training)", candidate_id)
    return candidate
```

Bandingkan dengan versi lama method ini — kalau sebelumnya ada baris yang
set `candidate.is_training_example = True` atau `candidate.actual_score =
settings.DISLIKED_CLIP_DEFAULT_SCORE`, **hapus kedua baris itu**. Method
`unmark_disliked()` di bawahnya boleh dibiarkan apa adanya (cuma reset
`label_source` balik ke `None`) — tidak perlu diubah karena tidak pernah
menyentuh `is_training_example`/`actual_score` sejak awal.

## Task — Hapus Konstanta yang Sudah Tidak Dipakai

Di `app/core/config/settings.py`, hapus baris `DISLIKED_CLIP_DEFAULT_SCORE`
sepenuhnya — sudah tidak dipakai di mana pun setelah perubahan ini.

## Definisi Selesai

- `python -m py_compile app/services/candidate_service.py app/core/config/settings.py`
  lulus.
- `grep -n "DISLIKED_CLIP_DEFAULT_SCORE" app/` hasilnya kosong total (baik
  di settings.py maupun pemakainya).
- Baca ulang method `mark_as_disliked()` — pastikan TIDAK ADA baris yang
  menyentuh `is_training_example` atau `actual_score` sama sekali.
- `pytest` tetap lulus.
- **Jangan lanjut ke file 12** sebelum poin di atas terverifikasi.
