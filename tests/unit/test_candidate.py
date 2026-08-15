"""Tests for CandidateService."""

from unittest.mock import MagicMock, patch

from app.models.candidate_model import CandidateModel
from app.services.candidate_service import CandidateService


def _make_chain(rows):
    """Return a mock that supports .join().filter().order_by().all() chains."""
    chain = MagicMock()
    chain.join.return_value = chain
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = rows
    return chain


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
    service.score_engine.select_top_n.return_value = [mock_candidate]

    candidates = service.generate_candidates(job_id=1, num_clips=3)

    assert len(candidates) == 1
    service.score_engine.calculate_for_job.assert_called_once_with(1)
    service.score_engine.select_top_n.assert_called_once_with(1, 3)


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

    mock_repo.update_status.return_value = mock_candidate
    result = service.select_candidate(1)

    assert result.status == "candidate"
    mock_repo.update_status.assert_called_once_with(1, "selected")


def test_get_video_summaries_excludes_training_ingest() -> None:
    """get_video_summaries() harus tidak tampilkan video yang cuma punya training_ingest candidate."""
    mock_db = MagicMock()
    service = CandidateService(mock_db)

    # Dua video di DB
    video_normal = MagicMock()
    video_normal.id = 1
    video_training = MagicMock()
    video_training.id = 2

    # Query VideoModel → kembalikan kedua video
    video_chain = MagicMock()
    video_chain.order_by.return_value = video_chain
    video_chain.all.return_value = [video_normal, video_training]

    # Candidate query untuk video_normal → 1 candidate (job discovery)
    cand_normal = MagicMock()
    cand_normal.final_score = 8.0
    cand_normal.label_source = None
    cand_normal.status = "candidate"

    chain_v1 = _make_chain([cand_normal])
    chain_v2 = _make_chain([])  # training_ingest di-filter keluar → 0 hasil

    def _query_side(model):
        from app.models.candidate_model import CandidateModel as CM
        from app.models.video_model import VideoModel as VM
        if model is VM:
            return video_chain
        if model is CM:
            # Kembalikan chain berbeda per call (video_normal dulu, lalu video_training)
            return next(candidate_chains)
        raise ValueError(f"Unexpected model: {model}")

    candidate_chains = iter([chain_v1, chain_v2])
    mock_db.query.side_effect = _query_side

    summaries = service.get_video_summaries()

    # Hanya video_normal yang muncul
    assert len(summaries) == 1
    assert summaries[0]["video"] is video_normal
    assert summaries[0]["candidate_count"] == 1


def test_list_by_video_excludes_training_ingest() -> None:
    """list_by_video() harus return list kosong untuk video training-only."""
    mock_db = MagicMock()
    service = CandidateService(mock_db)

    chain = _make_chain([])  # filter training_ingest → kosong
    mock_db.query.return_value = chain

    result = service.list_by_video(video_id=42)

    assert result == []


def test_list_by_video_returns_discovery_candidates() -> None:
    """list_by_video() harus return candidate dari job discovery."""
    mock_db = MagicMock()
    service = CandidateService(mock_db)

    mock_candidate = MagicMock()
    mock_candidate.final_score = 7.5

    chain = _make_chain([mock_candidate])
    mock_db.query.return_value = chain

    result = service.list_by_video(video_id=1)

    assert len(result) == 1
    assert result[0].final_score == 7.5

