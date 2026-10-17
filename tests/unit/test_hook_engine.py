"""Tests for HookMomentFinder — mock-based, tidak butuh API key atau video asli."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.ai_modules.hook_analysis.hook_moment_finder import HookMomentFinder, HookMoment


# ── Helper: buat mock segment ────────────────────────────────────────────────

def _seg(start: float, end: float, text: str) -> MagicMock:
    s = MagicMock()
    s.start_time = start
    s.end_time = end
    s.text = text
    return s


def _make_segments(n: int = 8, start_offset: float = 0.0) -> list:
    """Buat N segment dummy dengan interval 3 detik per segment."""
    return [
        _seg(start_offset + i * 3.0, start_offset + i * 3.0 + 2.5, f"Teks segment nomor {i}.")
        for i in range(n)
    ]


# ── a. Skip kalau segments < 4 ───────────────────────────────────────────────

def test_skip_if_segments_less_than_4() -> None:
    """Kalau segments < 4, langsung return None (window_too_short)."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = _make_segments(3)
    moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "window_too_short"


# ── b. Skip kalau tidak ada API key ──────────────────────────────────────────

def test_skip_if_no_api_key() -> None:
    """Tanpa API key → return None (llm_unavailable). TIDAK mock random."""
    finder = HookMomentFinder()
    finder.api_key = ""

    segs = _make_segments(8)
    moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "llm_unavailable"


# ── c. Skip kalau best_idx adalah segmen pembuka paling awal (index < 1) ─────

def test_skip_if_best_idx_too_close_by_index() -> None:
    """best_idx=0 (< 1, kalimat pembuka) → moment_too_close_to_start."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    llm_response = json.dumps({
        "best_idx": 0,
        "hook_type": "shock",
        "confidence": 0.9,
        "reason": "pembuka asli",
        "caption": "Ini menarik!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        segs = _make_segments(8)
        moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "moment_too_close_to_start"


# ── d. Skip kalau best_idx terlalu dekat ke awal (delta waktu < 2.5 detik) ───

def test_skip_if_best_idx_too_close_by_time() -> None:
    """Segment idx=2 tapi hanya 1.6 detik dari awal (< 2.5s) → moment_too_close_to_start."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    # Segment sangat rapat: setiap segment hanya 0.8 detik
    segs = [_seg(i * 0.8, i * 0.8 + 0.7, f"Teks {i}") for i in range(8)]
    # segs[2].start_time = 1.6 → delta = 1.6 - 0.0 = 1.6 < 2.5

    llm_response = json.dumps({
        "best_idx": 2,
        "hook_type": "stat",
        "confidence": 0.85,
        "reason": "fakta menarik",
        "caption": "Fakta mengejutkan!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "moment_too_close_to_start"


def test_early_mid_zone_idx_1_or_2_accepted() -> None:
    """Zona awal-menengah (idx 1 atau 2 setelah pembuka, delta_t >= 2.5s) diterima pada klip >= 8 segmen."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = _make_segments(8)  # segs[1].start_time = 3.0s (delta 3.0s >= 2.5s)
    llm_response = json.dumps({
        "best_idx": 1,
        "hook_type": "curiosity_gap",
        "confidence": 0.88,
        "reason": "pemicu penasaran tepat setelah intro",
        "caption": "Salah buka pintu terlarang!",
        "highlight_word": "terlarang",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert reason is None
    assert moment is not None
    assert moment.best_idx == 1
    assert moment.hook_moment_start == 3.0
    assert moment.highlight_word == "terlarang"


# ── e. Skip kalau confidence di bawah threshold ───────────────────────────────

def test_skip_if_confidence_below_threshold() -> None:
    """confidence=0.4 < AUTO_HOOK_MIN_CONFIDENCE (0.6) → low_confidence."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    llm_response = json.dumps({
        "best_idx": 5,
        "hook_type": "question",
        "confidence": 0.4,
        "reason": "rendah",
        "caption": "Kenapa?",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        segs = _make_segments(8)
        moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "low_confidence"


# ── f. Happy path: response LLM valid, semua guard lulus ─────────────────────

def test_happy_path_valid_llm_response() -> None:
    """Response LLM valid, best_idx jauh dari awal, confidence tinggi → HookMoment."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = _make_segments(10, start_offset=0.0)
    # segs[6].start_time = 18.0, delta dari segs[0].start_time=0 → 18.0 >= 5.0 ✓, idx=6 >= 3 ✓

    llm_response = json.dumps({
        "best_idx": 6,
        "hook_type": "shock",
        "confidence": 0.88,
        "reason": "klaim mengejutkan",
        "caption": "Kamu tidak akan percaya ini!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert moment is not None
    assert reason is None
    assert isinstance(moment, HookMoment)
    assert moment.hook_type == "shock"
    assert moment.hook_confidence == 0.88
    assert moment.hook_moment_start == segs[6].start_time
    # Durasi default 2.0s tapi akhir di-snap ke boundary segment
    # (akhir segmen yang memuat titik akhir) supaya tidak kepotong kalimat.
    assert moment.hook_moment_end == segs[6].end_time
    assert moment.hook_caption == "Kamu tidak akan percaya ini!"
    assert moment.best_idx == 6


def test_happy_path_with_audio_spikes() -> None:
    """audio_spikes metadata diteruskan ke HookMoment."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = _make_segments(10, start_offset=0.0)
    llm_response = json.dumps({
        "best_idx": 6,
        "hook_type": "shock",
        "confidence": 0.92,
        "reason": "teriakan kencang",
        "caption": "Reaksi tak terduga!",
    })

    audio_spikes = {
        "has_spike": True,
        "peak_time": 19.5,
        "peak_db": -4.2,
        "mean_db": -22.0,
    }

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs, audio_spikes=audio_spikes)

    assert moment is not None
    assert moment.has_audio_spike is True
    assert moment.audio_spike_time == 19.5
    assert moment.hook_type == "shock"



# ── g. Fallback caption kalau LLM tidak kirim caption ────────────────────────

def test_fallback_caption_when_empty() -> None:
    """caption kosong dari LLM → fallback ke 8 kata pertama teks segment."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = _make_segments(8)
    segs[5] = _seg(15.0, 17.5, "Ini adalah kalimat sangat panjang yang mengandung banyak kata penting.")

    llm_response = json.dumps({
        "best_idx": 5,
        "hook_type": "curiosity_gap",
        "confidence": 0.75,
        "reason": "menarik",
        "caption": "",  # kosong
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert moment is not None
    # Fallback: ambil 8 kata pertama dari segs[5].text
    assert len(moment.hook_caption) > 0
    assert len(moment.hook_caption.split()) <= 8


# ── h. Parse gagal → llm_unavailable ─────────────────────────────────────────

def test_parse_failure_returns_unavailable() -> None:
    """LLM response bukan JSON valid → return (None, 'llm_unavailable')."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    with patch.object(finder, "_call_llm", return_value="bukan json sama sekali"):
        segs = _make_segments(8)
        moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "llm_unavailable"


# ── i. Parse dengan markdown code fence ──────────────────────────────────────

def test_parse_with_markdown_fences() -> None:
    """LLM sering balut JSON dalam ```json ... ``` — harus bisa di-parse."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    raw = '```json\n{"best_idx": 4, "hook_type": "stat", "confidence": 0.82, "reason": "ok", "caption": "Fakta menarik sekali"}\n```'

    with patch.object(finder, "_call_llm", return_value=raw):
        segs = _make_segments(8)  # segs[4].start_time=12.0, delta=12 ≥ 5 ✓
        moment, reason = finder.find(segs)

    assert moment is not None
    assert moment.hook_caption == "Fakta menarik sekali"


# ── j. Parse tahan trailing junk setelah JSON (regresi 9router SSE artefak) ──

def test_parse_tolerates_trailing_text_after_json() -> None:
    """9Router/model kadang nambah teks atau `data: [DONE]` setelah JSON —
    parser harus ekstrak blok JSON dan abaikan sisa trailing."""

    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    raw = (
        '{"best_idx": 5, "hook_type": "conflict", "confidence": 0.85,'
        ' "reason": "klaim berani", "caption": "Gue beli lagi padahal nggak penting."}'
        '\n\nSebenarnya segmen yang paling menarik adalah nomor 5 karena memicu penasaran.\\nJadi jawabannya:'
    )

    with patch.object(finder, "_call_llm", return_value=raw):
        segs = _make_segments(10)  # segs[5].start_time=15.0, delta=15 ≥ 5 ✓
        moment, reason = finder.find(segs)

    assert moment is not None
    assert reason is None
    assert moment.best_idx == 5
    assert moment.hook_caption == "Gue beli lagi padahal nggak penting."


# ── l. hook_duration variabel + snap ke boundary segment ─────────────────────

def test_variable_hook_duration_snaps_to_segment_end() -> None:
    """LLM kirim hook_duration=4.0 → hook_akhir mengikuti sampai akhir segment
    yang memuat titik akhir (tidak terpotong di tengah kalimat), tapi tidak
    melewati akhir window."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = _make_segments(10)  # segs[6]=18.0-20.5, segs[7]=21.0-23.5
    # duration 4.0 → akhir 22.0, memuat segs[7] (21.0-23.5) → snap ke 23.5
    llm_response = json.dumps({
        "best_idx": 6,
        "hook_type": "stat",
        "confidence": 0.9,
        "reason": "fakta",
        "hook_duration": 4.0,
        "caption": "Fakta mengejutkan sekali!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert moment is not None
    assert reason is None
    assert moment.hook_moment_start == segs[6].start_time
    assert moment.hook_moment_end == segs[7].end_time
    assert moment.hook_moment_end >= segs[6].start_time + 2.0  # lebih panjang dari 2s kaku


# ── m. Caption bohong (angka baru) → fallback verbatim segment ───────────────

def test_false_caption_falls_back_to_verbatim() -> None:
    """LLM kirim caption dengan angka yang TIDAK ada di transkrip (misal
    transkrip bilang 6 juta, caption bilang 100 juta) → caption dibuang,
    pakai teks verbatim segment (dijamin jujur)."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = [
        _seg(i * 3.0, i * 3.0 + 2.5, f"Teks {i}.")
        for i in range(8)
    ]
    segs[5] = _seg(15.0, 17.5, "Harganya 6 juta rupiah per unitnya.")

    llm_response = json.dumps({
        "best_idx": 5,
        "hook_type": "shock",
        "confidence": 0.9,
        "reason": "angka besar",
        "caption": "Harganya 100 juta rupiah!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert moment is not None
    assert moment.hook_caption != "Harganya 100 juta rupiah!"
    assert "100 juta" not in moment.hook_caption
    assert "6 juta" in moment.hook_caption  # pakai teks asli transkrip


def test_true_caption_kept_when_number_matches_transcript() -> None:
    """Angka caption muncul di transkrip → caption LLM dipertahankan."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = [
        _seg(i * 3.0, i * 3.0 + 2.5, f"Teks {i}.")
        for i in range(8)
    ]
    segs[5] = _seg(15.0, 17.5, "Hal ini bisa lebih dari 6 juta orang setiap harinya.")

    llm_response = json.dumps({
        "best_idx": 5,
        "hook_type": "stat",
        "confidence": 0.8,
        "reason": "angka besar",
        "caption": "Gak nyangka 6 juta orang?",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert moment is not None
    assert moment.hook_caption == "Gak nyangka 6 juta orang?"


# ── _call_llm tahan trailing `data: [DONE]` di body HTTP 9router ─────────────

def test_call_llm_strips_sse_done_trailing() -> None:
    """Body HTTP 9router kadang berakhir `...}data: [DONE]` → _call_llm harus
    tetap return content model, bukan lempar Extra data."""

    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    payload_body = (
        '{"choices":[{"message":{"role":"assistant","content":'
        '"{\\"best_idx\\": 5, \\"hook_type\\": \\"conflict\\", \\"confidence\\": 0.85, \\"reason\\": \\"ok\\", \\"caption\\": \\"Test caption OK\\"}"}}]}'
        'data: [DONE]'
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {}
    mock_response.text = payload_body

    # Panggil _call_llm langsung dengan client di-mock
    with patch.object(finder.client, "post", return_value=mock_response):
        content = finder._call_llm("prompt dummy")

    parsed = json.loads(content)
    assert parsed["best_idx"] == 5
    assert parsed["caption"] == "Test caption OK"

    # Pastikan tidak butuh response.json() (yang akan gagal karena Extra data)
    mock_response.json.assert_not_called()


def test_short_trimmed_window_allows_idx_1() -> None:
    """Pada klip pendek hasil trim (< 8 segmen), best_idx=1 (delta >= 2.0s) harus diterima,
    bukan ditolak sebagai moment_too_close_to_start."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    # Buat 5 segment (klip durasi ~15 detik hasil trim)
    segs = _make_segments(5, start_offset=10.0)
    # segs[0]: 10.0 -> 12.5
    # segs[1]: 13.0 -> 15.5 (delta_t = 3.0s dari window_start)

    llm_response = json.dumps({
        "best_idx": 1,
        "hook_type": "curiosity_gap",
        "confidence": 0.85,
        "reason": "momen menarik di klip pendek",
        "caption": "Momen ini menarik!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert reason is None
    assert moment is not None
    assert moment.best_idx == 1
    assert moment.hook_moment_start == 13.0


def test_cliffhanger_cut_on_long_shock_segment() -> None:
    """Jika hook_type='shock' dan segmen terlalu panjang (> 3.8s), potong di hook_duration
    agar tidak membocorkan akhir situasi (anti-spoiler cliffhanger cut)."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    segs = _make_segments(8)
    # Buat segmen idx 4 berdurasi panjang (6.0 detik: 12.0 -> 18.0)
    segs[4] = _seg(12.0, 18.0, "Teriakan kaget panjang lalu diikuti penjelasan akhir cerita.")

    llm_response = json.dumps({
        "best_idx": 4,
        "hook_type": "shock",
        "confidence": 0.91,
        "hook_duration": 2.4,
        "reason": "puncak teriakan",
        "caption": "Detik terakhir bikin panik...",
        "highlight_word": "panik",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert reason is None
    assert moment is not None
    assert moment.hook_moment_start == 12.0
    # Harus dipotong di 12.0 + 2.4 = 14.4, bukan di-snap ke 18.0
    assert moment.hook_moment_end == pytest.approx(14.4)
    assert moment.highlight_word == "panik"

