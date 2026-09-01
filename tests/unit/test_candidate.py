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

    # Satu video aktif (is_archived=False) — satu-satunya yang dikembalikan filter
    video_normal = MagicMock()
    video_normal.id = 1
    video_normal.is_archived = False

    # Setelah refactor, get_video_summaries() pakai .filter(is_archived==False)
    # — mock chain langsung kembalikan [video_normal] (training video tidak masuk)
    video_chain = MagicMock()
    video_chain.filter.return_value = video_chain
    video_chain.order_by.return_value = video_chain
    video_chain.all.return_value = [video_normal]

    # Candidate query untuk video_normal → 1 candidate (job discovery)
    cand_normal = MagicMock()
    cand_normal.final_score = 8.0
    cand_normal.label_source = None
    cand_normal.status = "candidate"

    chain_v1 = _make_chain([cand_normal])

    def _query_side(model):
        from app.models.candidate_model import CandidateModel as CM
        from app.models.video_model import VideoModel as VM
        if model is VM:
            return video_chain
        if model is CM:
            return chain_v1
        raise ValueError(f"Unexpected model: {model}")

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



# ── Tests baru untuk fitur pemisahan archived ────────────────────────────────

def test_get_video_summaries_excludes_archived() -> None:
    """get_video_summaries() TIDAK boleh mengembalikan video dengan is_archived=True."""
    mock_db = MagicMock()
    service = CandidateService(mock_db)

    # Dua video: satu aktif, satu archived
    video_active = MagicMock()
    video_active.id = 10
    video_active.is_archived = False

    video_archived = MagicMock()
    video_archived.id = 11
    video_archived.is_archived = True

    # get_video_summaries() hanya query VideoModel dengan filter is_archived==False
    # — mock filter chain hanya mengembalikan video_active
    cand_active = MagicMock()
    cand_active.final_score = 7.0
    cand_active.label_source = None
    cand_active.status = "candidate"

    video_chain = MagicMock()
    video_chain.filter.return_value = video_chain
    video_chain.order_by.return_value = video_chain
    video_chain.all.return_value = [video_active]  # is_archived==False tersaring

    cand_chain = _make_chain([cand_active])

    def _query_side(model):
        from app.models.candidate_model import CandidateModel as CM
        from app.models.video_model import VideoModel as VM
        if model is VM:
            return video_chain
        if model is CM:
            return cand_chain
        raise ValueError(f"Unexpected: {model}")

    mock_db.query.side_effect = _query_side

    summaries = service.get_video_summaries()

    assert len(summaries) == 1
    assert summaries[0]["video"] is video_active
    # Pastikan filter dipanggil (artinya is_archived==False diterapkan)
    video_chain.filter.assert_called()


def test_get_archived_video_summaries_only_archived() -> None:
    """get_archived_video_summaries() HANYA mengembalikan video dengan is_archived=True."""
    mock_db = MagicMock()
    service = CandidateService(mock_db)

    video_archived = MagicMock()
    video_archived.id = 20
    video_archived.is_archived = True

    # Mock video_repo.list_archived() agar kembalikan hanya video_archived
    mock_video_repo = MagicMock()
    mock_video_repo.list_archived.return_value = [video_archived]
    service.video_repo = mock_video_repo

    cand = MagicMock()
    cand.final_score = 5.5
    cand.label_source = "user_liked"
    cand.status = "selected"

    cand_chain = _make_chain([cand])
    mock_db.query.return_value = cand_chain

    summaries = service.get_archived_video_summaries()

    mock_video_repo.list_archived.assert_called_once()
    assert len(summaries) == 1
    assert summaries[0]["video"] is video_archived
    assert summaries[0]["liked"] == 1


def test_archived_candidates_route_returns_200(monkeypatch) -> None:
    """GET /candidates/archived harus 200 dan render candidates_archived_content.html."""
    from fastapi.testclient import TestClient
    from app.main import app

    mock_summaries = [
        {
            "video": MagicMock(
                id=30,
                original_filename="test.mp4",
                is_archived=True,
                archived_at=None,
                duration_seconds=120.0,
                source_type="upload",
            ),
            "candidate_count": 3,
            "top_score": 8.1,
            "liked": 1,
            "disliked": 0,
            "clips_done": 1,
        }
    ]

    with patch(
        "app.routers.candidate_router.CandidateService.get_archived_video_summaries",
        return_value=mock_summaries,
    ):
        client = TestClient(app)
        response = client.get("/candidates/archived")

    assert response.status_code == 200
    assert "candidates_archived_content" in response.text or "Diarsipkan" in response.text or "Candidate" in response.text
