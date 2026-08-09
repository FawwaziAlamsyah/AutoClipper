"""Tests for CandidateService."""

from unittest.mock import MagicMock, patch

from app.models.candidate_model import Candidate
from app.services.candidate_service import CandidateService


def test_generate_candidates() -> None:
    """CandidateService should return top-N candidates."""
    mock_db = MagicMock()
    service = CandidateService(mock_db)

    mock_candidate = MagicMock()
    mock_candidate.id = 1
    mock_candidate.video_id = 1
    mock_candidate.job_id = 1
    mock_candidate.start_time = 10.0
    mock_candidate.end_time = 45.0
    mock_candidate.final_score = 85.0
    mock_candidate.hook_text = "Amazing moment"
    mock_candidate.status = "candidate"

    mock_repo = MagicMock()
    mock_repo.get_by_job.return_value = [mock_candidate, MagicMock()]
    service.candidate_repo = mock_repo
    service.score_engine = MagicMock()

    candidates = service.generate_candidates(job_id=1, num_clips=3)

    assert len(candidates) == 2
    mock_repo.get_by_job.assert_called_once_with(1)


def test_select_candidate() -> None:
    """CandidateService should mark candidate as selected."""
    mock_db = MagicMock()
    service = CandidateService(mock_db)

    mock_candidate = MagicMock()
    mock_candidate.id = 1
    mock_candidate.status = "candidate"

    mock_repo = MagicMock()
    mock_repo.get.return_value = mock_candidate
    service.candidate_repo = mock_repo

    result = service.select_candidate(1)

    assert result.status == "selected"
    mock_db.commit.assert_called_once()
