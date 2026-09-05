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


# ── c. Skip kalau best_idx terlalu dekat ke awal (index < 3) ─────────────────

def test_skip_if_best_idx_too_close_by_index() -> None:
    """best_idx=1 (< 3) → moment_too_close_to_start."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    llm_response = json.dumps({
        "best_idx": 1,
        "hook_type": "shock",
        "confidence": 0.9,
        "reason": "dekat awal",
        "caption": "Ini menarik!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        segs = _make_segments(8)
        moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "moment_too_close_to_start"


# ── d. Skip kalau best_idx terlalu dekat ke awal (delta waktu < 5 detik) ─────

def test_skip_if_best_idx_too_close_by_time() -> None:
    """Segment idx=3 tapi hanya 4 detik dari awal → moment_too_close_to_start."""
    finder = HookMomentFinder()
    finder.api_key = "dummy-key"

    # Segment sangat rapat: setiap segment hanya 1.2 detik
    segs = [_seg(i * 1.2, i * 1.2 + 1.0, f"Teks {i}") for i in range(8)]
    # segs[3].start_time = 3.6 → delta = 3.6 - 0.0 = 3.6 < 5.0

    llm_response = json.dumps({
        "best_idx": 3,
        "hook_type": "stat",
        "confidence": 0.85,
        "reason": "fakta menarik",
        "caption": "Fakta mengejutkan!",
    })

    with patch.object(finder, "_call_llm", return_value=llm_response):
        moment, reason = finder.find(segs)

    assert moment is None
    assert reason == "moment_too_close_to_start"


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

    with patch.object(finder, "_call_llm", return_value=None):
        pass

    # Panggil _call_llm langsung dengan client di-mock
    with patch.object(finder.client, "post", return_value=mock_response):
        content = finder._call_llm("prompt dummy")

    parsed = json.loads(content)
    assert parsed["best_idx"] == 5
    assert parsed["caption"] == "Test caption OK"

    # Pastikan tidak butuh response.json() (yang akan gagal karena Extra data)
    mock_response.json.assert_not_called()
