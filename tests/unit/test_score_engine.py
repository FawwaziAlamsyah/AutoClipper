"""Tests for ScoreEngine."""

from unittest.mock import MagicMock, patch

from app.services.score_engine import ScoreEngine


def test_calculate_score_breakdown() -> None:
    """ScoreEngine should aggregate weighted scores correctly."""
    mock_db = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_job.return_value = [
        MagicMock(analyzer_type="hook", score=8.0, start_time=0.0, end_time=10.0, result_data={"reason": "Pembuka kuat"}),
        MagicMock(analyzer_type="story", score=7.0, start_time=0.0, end_time=10.0, result_data={"reason": "Alur jelas"}),
        MagicMock(analyzer_type="llm_content", score=6.0, start_time=0.0, end_time=10.0, result_data={"reason": "Konten LLM"}),
        MagicMock(analyzer_type="voice_emotion", score=5.0, start_time=0.0, end_time=10.0, result_data={"reason": "Vokal netral"}),
        MagicMock(analyzer_type="face_emotion", score=4.0, start_time=0.0, end_time=10.0, result_data={"reason": "Wajah minim"}),
    ]

    with patch("app.services.score_engine.VideoRepository") as MockVideoRepo, \
         patch("app.services.score_engine.JobRepository") as MockJobRepo, \
         patch("app.services.score_engine.AnalysisResultRepository") as MockAnalysisRepo, \
         patch("app.services.score_engine.CandidateRepository") as MockCandidateRepo:
        MockAnalysisRepo.return_value = mock_repo
        engine = ScoreEngine(mock_db)
        engine.analysis_repo = mock_repo

        candidate = MagicMock(start_time=0.0, end_time=10.0)
        breakdown = engine._calculate_score_breakdown(job_id=1, candidate=candidate)

        assert "llm_content" in breakdown
        assert "hook" in breakdown
        assert "story" in breakdown

        # Shape baru: dict-of-dicts dengan score/weight/contribution/reason
        hook = breakdown["hook"]
        assert set(hook) == {"score", "weight", "contribution", "reason"}
        assert hook["score"] == 8.0
        assert hook["contribution"] == round(8.0 * hook["weight"], 2)
        assert hook["reason"] == "Pembuka kuat"


def test_score_differs_per_candidate_window() -> None:
    """Regression test: dua candidate window beda HARUS skor beda (bukan rata-rata global).

    Bug: analysis difilter per window. Tanpa filter, semua candidate dapat
    final_score identik (rata-rata seluruh job).
    """
    mock_db = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_by_job.return_value = [
        # Window A (0-10s): hook tinggi
        MagicMock(analyzer_type="hook", score=9.0, start_time=0.0, end_time=10.0, result_data={"reason": "A"}),
        # Window B (100-110s): hook rendah
        MagicMock(analyzer_type="hook", score=3.0, start_time=100.0, end_time=110.0, result_data={"reason": "B"}),
    ]

    with patch("app.services.score_engine.VideoRepository"), \
         patch("app.services.score_engine.JobRepository"), \
         patch("app.services.score_engine.AnalysisResultRepository"), \
         patch("app.services.score_engine.CandidateRepository"):
        engine = ScoreEngine(mock_db)
        engine.analysis_repo = mock_repo

        cand_a = MagicMock(start_time=0.0, end_time=10.0)
        cand_b = MagicMock(start_time=100.0, end_time=110.0)
        bd_a = engine._calculate_score_breakdown(1, cand_a)
        bd_b = engine._calculate_score_breakdown(1, cand_b)

        score_a = sum(v["contribution"] for k, v in bd_a.items() if k != "_meta")
        score_b = sum(v["contribution"] for k, v in bd_b.items() if k != "_meta")

        assert score_a != score_b, f"skor harus beda per window: A={score_a}, B={score_b}"
        assert bd_a["hook"]["score"] == 9.0
        assert bd_b["hook"]["score"] == 3.0
