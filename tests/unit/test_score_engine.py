"""Tests for ScoreEngine."""

from unittest.mock import MagicMock, patch

from app.services.score_engine import ScoreEngine


def test_calculate_score_breakdown() -> None:
    """ScoreEngine should aggregate weighted scores correctly."""
    mock_db = MagicMock()

    mock_repo = MagicMock()
    mock_repo.get_by_job.return_value = [
        MagicMock(analyzer_type="hook", score=8.0),
        MagicMock(analyzer_type="story", score=7.0),
        MagicMock(analyzer_type="llm_content", score=6.0),
        MagicMock(analyzer_type="voice_emotion", score=5.0),
        MagicMock(analyzer_type="face_emotion", score=4.0),
    ]

    with patch("app.services.score_engine.VideoRepository") as MockVideoRepo, \
         patch("app.services.score_engine.JobRepository") as MockJobRepo, \
         patch("app.services.score_engine.AnalysisResultRepository") as MockAnalysisRepo, \
         patch("app.services.score_engine.CandidateRepository") as MockCandidateRepo:
        MockAnalysisRepo.return_value = mock_repo
        engine = ScoreEngine(mock_db)
        engine.analysis_repo = mock_repo

        breakdown = engine._calculate_score_breakdown(job_id=1, candidate_id=1)

        assert "llm_content" in breakdown
        assert "hook" in breakdown
        assert "story" in breakdown
