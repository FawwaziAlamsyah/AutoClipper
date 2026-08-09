"""Tests for Prompt E fixes: sliding window overlap + non-overlap selection."""

from unittest.mock import MagicMock

from app.services.analysis_service import AnalysisService
from app.services.score_engine import ScoreEngine


class _Seg:
    def __init__(self, start: float, end: float, text: str = "x") -> None:
        self.start_time = start
        self.end_time = end
        self.text = text


def test_build_windows_slides_across_whole_video() -> None:
    """Windows harus menyapu seluruh durasi, bukan cuma awal video."""
    segments = [_Seg(i * 10, i * 10 + 9) for i in range(10)]  # 0-99s, segmen 10 detik
    svc = AnalysisService(MagicMock())

    windows = svc._build_windows(segments, min_dur=20, max_dur=30)

    assert len(windows) > 3, "harus ada banyak window (bukan cuma num_clips awal)"
    assert windows[0]["start"] == 0.0
    # Window terakhir harus dekat akhir video, bukan berhenti di detik awal
    assert windows[-1]["start"] > 50.0
    # Overlap: window berikutnya mulai sebelum window sebelumnya berakhir
    assert windows[1]["start"] < windows[0]["end"]


def test_build_windows_ignores_short_tail() -> None:
    """Window terakhir yang kepotong < min_dur dibuang."""
    segments = [_Seg(i * 10, i * 10 + 9) for i in range(3)]  # 0-29s
    svc = AnalysisService(MagicMock())

    windows = svc._build_windows(segments, min_dur=25, max_dur=30)

    assert all(w["end"] - w["start"] >= 25 for w in windows)


def test_select_top_n_no_overlap() -> None:
    """Top-N hasilnya tidak boleh saling overlap waktunya."""
    engine = ScoreEngine(MagicMock())

    cands = [
        MagicMock(id=1, start_time=0.0, end_time=30.0, final_score=90.0),
        MagicMock(id=2, start_time=25.0, end_time=55.0, final_score=88.0),  # overlap #1
        MagicMock(id=3, start_time=60.0, end_time=90.0, final_score=85.0),
        MagicMock(id=4, start_time=10.0, end_time=40.0, final_score=95.0),  # overlap #1, skor tertinggi
    ]
    engine.candidate_repo = MagicMock()
    engine.candidate_repo.get_by_job.return_value = cands
    engine.db = MagicMock()

    selected = engine.select_top_n(1, n=3)

    # Non-overlap suppression: yang overlap dengan top dipilih lebih dulu diskip
    kept = selected
    for i in range(len(kept)):
        for j in range(i + 1, len(kept)):
            a, b = kept[i], kept[j]
            assert not (a.start_time < b.end_time and b.start_time < a.end_time), \
                f"candidate {a.id} & {b.id} overlap"


def test_calculate_breakdown_excludes_inactive_analyzer() -> None:
    """Analyzer tanpa result di seluruh job di-exclude dari breakdown."""
    engine = ScoreEngine(MagicMock())
    mock_repo = MagicMock()
    # Hanya hook & story yang punya result — llm_content TIDAK ada di job
    mock_repo.get_by_job.return_value = [
        MagicMock(analyzer_type="hook", score=8.0, start_time=0.0, end_time=10.0, result_data={"reason": "Pembuka kuat"}),
        MagicMock(analyzer_type="story", score=7.0, start_time=0.0, end_time=10.0, result_data={"reason": "Alur jelas"}),
    ]
    engine.analysis_repo = mock_repo

    breakdown = engine._calculate_score_breakdown(1, MagicMock(start_time=0.0, end_time=10.0))

    assert "hook" in breakdown
    assert "story" in breakdown
    assert "llm_content" not in breakdown, "llm_content tak aktif di job → harus di-exclude"
