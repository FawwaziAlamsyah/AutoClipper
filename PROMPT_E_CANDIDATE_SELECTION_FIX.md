# Prompt E — Candidate Window Generation & Scoring Fix

Konteks untuk AI yang mengerjakan: project AI Auto Clipper sudah melewati Tahap A–D
(layering rapi, `ai_modules/` plugin-ready). Tapi hasil candidate clip yang muncul di UI
tidak masuk akal: window-nya cuma potongan berurutan dari detik awal video (4.5–64.5,
64.5–124.5, 124.5–184.5, dst — semua persis durasi sama, nempel tanpa gap), dan
`final_score` SEMUA candidate dalam satu job identik sampai 2 desimal (mis. 6.54).
Ini bukti bahwa sistem tidak benar-benar men-scan seluruh video untuk cari momen
terbaik — ini cuma memotong video secara linear dan memberi skor yang sama rata.

Root cause SUDAH DIKONFIRMASI dari `app/services/analysis_service.py` dan
`app/services/score_engine.py` — lihat penjelasan tiap task. **Jangan menebak ulang
akar masalahnya, langsung kerjakan fix di bawah.**

Kerjakan task secara berurutan (0 → 4). Tiap task harus tetap membuat aplikasi
runnable, jangan gabungkan semua jadi satu commit besar.

---

## Task 0 — Baca `app/services/validators.py` Sebelum Mulai

File ini belum sempat direview di sesi analisis sebelumnya. Sebelum mengerjakan Task 2,
baca isinya dan pastikan:
- Apakah `run_all_validators(text, keywords, skip_keywords)` benar-benar menghasilkan
  skor yang bervariasi tergantung ISI `text` (mis. keyword matching, sentiment kata,
  panjang kalimat), atau ada kemungkinan dia mengembalikan nilai default/statis untuk
  kategori tertentu (`hook`, `story`, `context`, `ending`, `viral`) terlepas dari isi teks.
- Catat temuan ini di awal PR/commit sebagai bagian dari root-cause, karena ini
  kontributor kedua ke masalah "skor identik" selain fallback 0.5 di Task 2.

---

## Task 1 — Ganti Window Generation dari Sequential Chop Jadi Sliding Window Menyeluruh

### Bug yang dikonfirmasi

Di `app/services/analysis_service.py`, method `_build_windows()`:

```python
target = min(max_dur, max(min_dur, total_duration / max(num_clips, 1)))
windows = []
cursor = segments[0].start_time

while len(windows) < num_clips and cursor < segments[-1].end_time:
    win_start = cursor
    win_end = min(cursor + target, segments[-1].end_time)
    win_segments = [s for s in segments if s.start_time >= win_start and s.start_time < win_end]
    if win_segments:
        windows.append({"start": win_start, "end": win_end, "segments": win_segments})
    cursor = win_end   # <-- cursor lompat ke UJUNG window, tidak overlap, tidak scan ulang
```

Masalah: `cursor = win_end` membuat window berikutnya selalu mulai persis di akhir window
sebelumnya. Ini memotong video secara linear dari awal sampai `num_clips` window
terkumpul (atau video habis) — bukan mencari window terbaik di seluruh durasi video.

### Perbaikan

Ganti jadi **sliding window dengan overlap**, men-scan SELURUH durasi video (bukan
berhenti begitu `num_clips` window terkumpul), sehingga scoring di Task 2 punya banyak
kandidat asli untuk dibandingkan, bukan cuma potongan pertama yang kebetulan muat.

```python
def _build_windows(
    self,
    segments: list,
    min_dur: float,
    max_dur: float,
    stride_ratio: float = 0.5,
) -> list[dict]:
    """Scan seluruh transcript dengan sliding window yang overlap.

    Window duration = max_dur (durasi target terpanjang yang diizinkan).
    Stride (jarak antar window) = stride_ratio * window duration, sehingga
    window saling overlap dan tidak ada bagian video yang terlewat begitu
    saja hanya karena posisinya di tengah/akhir video.

    Tidak dibatasi num_clips di sini — semua window kandidat dihasilkan,
    lalu score_engine.select_top_n() yang memilih & menghapus non-top setelah
    scoring (lihat Task 3 untuk penyesuaian pemanggilnya).
    """
    if not segments:
        return []

    video_start = segments[0].start_time
    video_end = segments[-1].end_time
    window_dur = max_dur
    stride = max(window_dur * stride_ratio, 1.0)

    windows = []
    cursor = video_start
    while cursor < video_end:
        win_start = cursor
        win_end = min(cursor + window_dur, video_end)

        # Buang window terakhir yang kepotong terlalu pendek (di bawah min_dur),
        # KECUALI itu satu-satunya window yang ada.
        if (win_end - win_start) < min_dur and windows:
            break

        win_segments = [
            s for s in segments
            if s.start_time < win_end and s.end_time > win_start
        ]
        if win_segments:
            windows.append({"start": win_start, "end": win_end, "segments": win_segments})

        cursor += stride

    return windows
```

Perubahan penting dari versi lama:
- Parameter `num_clips` **dihapus** dari `_build_windows` — jumlah window sekarang murni
  ditentukan oleh durasi video / stride, bukan dipatok dari awal.
- Filter segmen pakai overlap check (`s.start_time < win_end and s.end_time > win_start`),
  bukan `s.start_time >= win_start and s.start_time < win_end` — supaya segmen yang
  overlap sebagian dengan window tetap ikut terhitung.
- `cursor += stride` (bukan `cursor = win_end`) — inilah yang membuat window saling
  overlap dan benar-benar menyapu seluruh durasi video.

### Update pemanggil di `analyze_job()`

Baris ini di `analyze_job()`:

```python
windows = self._build_windows(segments, num_clips * _WINDOW_BATCH, min_dur, max_dur)
```

Ganti jadi:

```python
windows = self._build_windows(segments, min_dur, max_dur)
```

Hapus juga konstanta `_WINDOW_BATCH` yang sudah tidak dipakai, dan hapus komentar terkait
"Generate window lebih banyak dari num_clips" di atasnya (sudah tidak relevan — sekarang
window dihasilkan dari seluruh video, bukan kelipatan num_clips).

### Batas wajar (safety limit)

Untuk video yang sangat panjang, sliding window per 30–50% overlap bisa menghasilkan
window dalam jumlah besar (video 1 jam ÷ stride 30 detik ≈ 120 window), yang berarti
120× pemanggilan validator + plugin analyzer per job. Tambahkan cap:

```python
MAX_WINDOWS_PER_JOB = 150  # sesuaikan sesuai kapasitas server

# di akhir _build_windows, sebelum return:
if len(windows) > MAX_WINDOWS_PER_JOB:
    # Downsample merata, tetap cover seluruh durasi video
    step = len(windows) / MAX_WINDOWS_PER_JOB
    windows = [windows[int(i * step)] for i in range(MAX_WINDOWS_PER_JOB)]
```

---

## Task 2 — Perbaiki Scoring Supaya Tidak Seragam

### Bug yang dikonfirmasi

Di `app/services/score_engine.py`, method `_get_analyzer_score()`:

```python
def _get_analyzer_score(self, analysis: list, analyzer_type: str) -> float:
    results = [a for a in analysis if a.analyzer_type == analyzer_type]
    if not results:
        return 0.5  # Default neutral score
    return sum(r.score or 0 for r in results) / len(results)
```

Kalau sebuah analyzer_type (mis. `llm_content`, bobot 30% — TERBESAR) tidak menghasilkan
result sama sekali untuk SATU window tertentu, window itu dapat skor default 0.5 untuk
kategori itu — flat, sama untuk semua window yang mengalami hal serupa. Kalau ini terjadi
di banyak kategori sekaligus (mis. karena API key LLM kosong, atau `video_path`/`audio_path`
tidak valid sehingga `face_emotion`/`voice_emotion`/dst selalu gagal di SEMUA window),
mayoritas bobot skor akhirnya jadi konstanta yang sama di semua candidate — persis gejala
di screenshot Anda.

### Perbaikan A — Ubah fallback dari "0.5 per window" jadi "exclude dari total per job"

Alih-alih tiap window dapat 0.5 untuk kategori yang analyzer-nya gagal, cek dulu: kalau
analyzer_type tersebut TIDAK PERNAH menghasilkan result di seluruh job (bukan cuma window
ini), berarti analyzer itu memang tidak aktif untuk job ini — jangan ikutkan bobotnya sama
sekali (supaya tidak mencemari semua window dengan angka konstan yang sama).

Di `_calculate_score_breakdown()`, sebelum loop `for analyzer_type, weight in weights.items()`,
tambahkan pre-check:

```python
def _calculate_score_breakdown(self, job_id: int, candidate_id: int) -> dict[str, dict]:
    analysis = self.analysis_repo.get_by_job(job_id)

    # Analyzer yang sama sekali tidak punya result di seluruh job ini dianggap
    # tidak aktif untuk job ini — bobotnya di-exclude, BUKAN diberi nilai netral
    # ke semua window (itu yang menyebabkan skor jadi seragam).
    active_types = {a.analyzer_type for a in analysis}

    weights = {
        "llm_content": settings.SCORE_WEIGHT_LLM_CONTENT,
        "hook": settings.SCORE_WEIGHT_HOOK,
        "story": settings.SCORE_WEIGHT_STORY,
        "voice_emotion": settings.SCORE_WEIGHT_VOICE_EMOTION,
        "face_emotion": settings.SCORE_WEIGHT_FACE_EMOTION,
        "gesture": settings.SCORE_WEIGHT_GESTURE,
        "eye_contact": settings.SCORE_WEIGHT_EYE_CONTACT,
        "scene": settings.SCORE_WEIGHT_SCENE,
        "audio": settings.SCORE_WEIGHT_AUDIO,
        "context": settings.SCORE_WEIGHT_CONTEXT,
        "ending": settings.SCORE_WEIGHT_ENDING,
    }

    breakdown = {}
    for analyzer_type, weight in weights.items():
        if weight <= 0 or analyzer_type not in active_types:
            continue
        score = self._get_analyzer_score(analysis, analyzer_type)
        breakdown[analyzer_type] = {
            "score": score,
            "weight": weight,
            "contribution": round(score * weight, 2),
            "reason": self._get_reason(analysis, analyzer_type),
        }
    ...
```

Untuk window yang punya result_data tapi kosong (analyzer aktif tapi gagal di window
spesifik ini saja), `_get_analyzer_score` masih boleh fallback 0.5 — itu wajar (perlakukan
sebagai "tidak yakin" untuk window itu saja), yang tidak boleh adalah men-default 0.5 ke
SEMUA window ketika analyzer-nya memang tidak pernah jalan sama sekali di job tersebut.

### Perbaikan B — Tambahkan logging diagnostik (sementara, boleh di-set DEBUG level)

Di `app/services/analysis_service.py`, akhir `_run_plugin_analyzers()`, sudah ada:

```python
self.job_service.finish_step(job_id, analyzer_type, success=any_result)
logger.debug("Analyze process: step %s success=%s", analyzer_type, any_result)
```

Ubah supaya melaporkan berapa window yang BENAR-BENAR berhasil vs total, bukan cuma
boolean any_result — supaya kalau nanti muncul kasus serupa, Anda bisa lihat langsung
dari `app.log` tanpa harus reverse-engineer lagi:

```python
success_count = 0
total_windows = 0
for i, window in enumerate(windows):
    input_data = build(window, i)
    if input_data is None:
        continue
    total_windows += 1
    try:
        result = analyzer.analyze(input_data)
    except AnalyzerUnavailable as e:
        logger.warning("Skip analyzer %s di window %d: %s", analyzer_type, i, e)
        continue
    self.analysis_repo.add(AnalysisResultModel(...))
    success_count += 1

self.job_service.finish_step(job_id, analyzer_type, success=success_count > 0)
logger.info(
    "Analyzer %s: %d/%d window berhasil untuk job %d",
    analyzer_type, success_count, total_windows, job_id,
)
```

Setelah fix ini jalan, cek `logs/app.log` saat memproses video test — kalau ada baris
seperti `Analyzer llm_content: 0/12 window berhasil`, itu konfirmasi analyzer tersebut
memang mati total (cek API key/config-nya), bukan cuma masalah scoring.

### Perbaikan C — Pastikan validator teks (Task 0) benar-benar bervariasi

Kalau dari Task 0 ternyata `run_all_validators()` memang menghasilkan skor statis untuk
sebagian kategori (bukan cuma masalah analyzer plugin), perbaiki di situ juga — skor
`hook`/`story`/`context`/`ending` harus berubah sesuai isi `text` window (panjang, ada/
tidaknya keyword, dst), bukan nilai tetap.

---

## Task 3 — Selaraskan `num_clips`, Selection, dan Overlap Suppression

Setelah Task 1, window sekarang overlap satu sama lain (mis. window 0–60s dan window
30–90s bisa sama-sama punya skor tinggi karena kontennya memang tumpang tindih). Kalau
`select_top_n()` di `score_engine.py` cuma sort by score tanpa cek overlap, hasil top-5
bisa berisi klip yang isinya nyaris sama (cuma geser beberapa detik) — bukan 5 momen
berbeda.

### Perbaikan — Non-overlap suppression saat pilih top-N

Di `app/services/score_engine.py`, ubah `select_top_n()`:

```python
def select_top_n(self, job_id: int, n: int) -> list:
    """Simpan top-n candidate dengan final_score tertinggi, TANPA overlap satu
    sama lain (non-max suppression berbasis waktu), hapus sisanya.
    """
    candidates = self.candidate_repo.get_by_job(job_id)
    if not candidates:
        return []

    ranked = sorted(candidates, key=lambda c: c.final_score or 0.0, reverse=True)

    selected: list = []
    for cand in ranked:
        overlaps = any(
            cand.start_time < kept.end_time and cand.end_time > kept.start_time
            for kept in selected
        )
        if not overlaps:
            selected.append(cand)
        if len(selected) >= n:
            break

    drop = [c for c in candidates if c not in selected]
    drop_ids = [c.id for c in drop]
    if drop_ids:
        self.db.query(ClipModel).filter(ClipModel.candidate_id.in_(drop_ids)).delete(synchronize_session=False)
        self.db.query(CandidateModel).filter(CandidateModel.id.in_(drop_ids)).delete(synchronize_session=False)
        self.db.commit()
        logger.info("Dropped %d overlapping/low-score candidate(s) dari job %d, simpan top %d", len(drop_ids), job_id, len(selected))

    return selected
```

### Pastikan `select_top_n` benar-benar dipanggil

Cek `app/services/process_service.py` (belum sempat direview di sesi analisis
sebelumnya) — pastikan alur job memanggil urutan ini dengan benar:

```
analyze_job()          → hasilkan SEMUA window sebagai candidate (skor masih 0.0)
score_engine.calculate_for_job()  → isi final_score & score_breakdown tiap candidate
score_engine.select_top_n(job_id, num_clips)  → filter jadi top-N non-overlap, hapus sisanya
```

Kalau `select_top_n` ternyata belum pernah dipanggil di pipeline manapun (dead code
seperti kasus `llm_service.py` sebelumnya), sambungkan pemanggilannya di
`process_service.py` setelah tahap scoring, dan hapus logika `candidates[:num_clips]`
yang lama di `candidate_service.generate_candidates()` (baris `candidates =
candidates[:num_clips]`) karena itu cuma slice biasa tanpa mempertimbangkan overlap —
sudah digantikan oleh `select_top_n`.

---

## Task 4 — Verifikasi

Setelah Task 1–3 selesai, jalankan pipeline pada satu video test (idealnya video dengan
konten yang jelas beda-beda per bagian, misal video 3–5 menit) dan cek:

1. **Sebaran waktu window**: candidate yang tersisa setelah `select_top_n` harus punya
   `start_time` yang tersebar di berbagai bagian video (awal/tengah/akhir), bukan
   berurutan rapi dari detik 0.
2. **Variasi skor**: `final_score` antar candidate harus berbeda (bukan sama sampai 2
   desimal seperti sebelumnya) — kecuali memang kebetulan videonya sangat homogen.
3. **Tidak ada overlap**: rentang waktu antar candidate yang tersisa tidak boleh saling
   tumpang tindih.
4. **Cek `logs/app.log`**: baris `Analyzer <type>: X/Y window berhasil` untuk tiap
   plugin analyzer — pastikan minimal analyzer utama (`llm_content` kalau API key sudah
   diisi) menunjukkan angka berhasil > 0, bukan 0/Y di semua window.

## Definisi Selesai

- `_build_windows()` menyapu seluruh durasi video dengan sliding window overlap, tidak
  lagi berhenti di `num_clips` window pertama.
- Fallback skor 0.5 tidak lagi diterapkan ke semua window saat analyzer benar-benar mati
  untuk satu job — bobotnya di-exclude dari breakdown.
- `select_top_n()` melakukan non-overlap suppression, bukan cuma sort-and-slice.
- `process_service.py` memanggil `analyze_job → calculate_for_job → select_top_n` secara
  berurutan, dan `candidate_service.generate_candidates()` tidak lagi melakukan
  `candidates[:num_clips]` manual.
- Hasil verifikasi Task 4 di atas terpenuhi pada minimal satu video test nyata.
