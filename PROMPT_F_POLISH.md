# Prompt F — Polish Minor (Opsional)

Konteks: Prompt A–E sudah diverifikasi sesuai — semua fix inti (sliding window,
scoring, non-overlap selection, layering, AI plugin, progress tracker, UI)
sudah benar. Tiga item di bawah ini murni polish, **tidak mendesak**, kerjakan
kalau ada waktu luang.

## 1. Hindari skor LLM konstan saat API key kosong

`app/ai_modules/llm_analysis/llm_analyzer.py`, method `_mock_analysis()`
mengembalikan angka tetap (`hook_score: 6.5, story_score: 7.0, dst`) untuk
SEMUA window ketika `LLM_API_KEY` tidak diisi. `llm_content` adalah bobot
terbesar (30%), jadi kalau API key belum diisi, 30% skor akhir jadi konstan
di semua candidate.

Perbaikan sederhana: buat mock score sedikit bervariasi berdasarkan isi
`transcript_text` (mis. panjang teks, jumlah kata unik, atau reuse sebagian
logic dari `validators.py`), supaya walau tanpa API key, urutan ranking
candidate tetap masuk akal — bukan menambah akurasi LLM sungguhan, cuma
mencegah 30% bobot jadi angka mati.

## 2. Format tampilan Score Breakdown di `candidate_detail.html`

Saat ini kolom "Kontribusi" menampilkan dict Python mentah dari
`score_breakdown` (`{{ value }}`). Ubah jadi kolom terpisah: Score, Weight,
Contribution, Reason — supaya lebih mudah dibaca tanpa harus mem-parse dict
di kepala.

```html
<tr>
  <td>{{ name }}</td>
  <td>{{ value.score }}</td>
  <td>{{ (value.weight * 100) | round(0) }}%</td>
  <td>{{ value.contribution }}</td>
  <td class="text-muted small">{{ value.reason }}</td>
</tr>
```

## 3. Rapikan total bobot skor jadi 1.0

Total `SCORE_WEIGHT_*` di `settings.py` sekarang 0.95 (bukan 1.0), jadi
`final_score` maksimal teoretis ~9.5 dari skala 10. Tidak merusak ranking,
tapi kalau mau `final_score` benar-benar dalam rentang 0–10, sesuaikan salah
satu bobot (mis. `SCORE_WEIGHT_STORY` dari 0.15 → 0.20) supaya total pas 1.0.

## Definisi Selesai

- Mock LLM score tidak lagi identik di semua window saat API key kosong.
- Score breakdown di UI tampil sebagai kolom terpisah, bukan dict mentah.
- Total `SCORE_WEIGHT_*` = 1.0 (opsional, boleh dilewati kalau skala 0-9.5
  sudah dianggap cukup).
