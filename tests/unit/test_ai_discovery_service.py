"""Unit tests for AIDiscoveryService."""

from unittest.mock import MagicMock
import pytest

from app.models.candidate_model import CandidateModel
from app.services.ai_discovery_service import AIDiscoveryService


def test_validate_and_persist_candidates():
    """Test validasi, snapping, eliminasi overlap, dan penyimpanan kandidat AI."""
    mock_db = MagicMock()
    service = AIDiscoveryService(mock_db)

    # Mock video dan job
    video = MagicMock(id=1, duration_seconds=120.0)
    job = MagicMock(id=10, category_id=None)

    # Mock transcript segments
    seg1 = MagicMock(id=1, start_time=10.0, end_time=18.0, text="Halo ini pembuka menarik")
    seg2 = MagicMock(id=2, start_time=18.0, end_time=32.0, text="Lalu terjadi sesuatu yang gila")
    seg3 = MagicMock(id=3, start_time=32.0, end_time=45.0, text="Ini punchline yang pecah abis")
    segments = [seg1, seg2, seg3]

    # Scene cuts
    scene_cuts = [9.5, 30.0, 46.0]

    curation_result = {
        "category_interpretation": "Analisis Konten Komedi",
        "candidates": [
            {
                "start_seg": 1,
                "end_seg": 3,
                "title": "Momen Ngakak Pecah Abis",
                "archetype": "funny_reaction",
                "why_viral": "Setup rapi dengan punchline tak terduga",
                "confidence": 8.8,
                "hook": {
                    "moment_time": 33.0,
                    "type": "shock",
                    "caption": "PUNCHLINE GILA!",
                },
            },
            # Kandidat kedua: overlap > 50% dengan skor lebih rendah -> harus dibuang
            {
                "start_seg": 2,
                "end_seg": 3,
                "title": "Potongan Sebagian",
                "archetype": "highlight",
                "why_viral": "Kurang lengkap",
                "confidence": 7.0,
            },
        ],
    }

    # Mock candidate_repo.add to return the model passed in
    service.candidate_repo.add = MagicMock(side_effect=lambda c: c)

    candidates = service._validate_and_persist_candidates(
        video=video,
        job=job,
        curation_result=curation_result,
        segments=segments,
        scene_cuts=scene_cuts,
    )

    # Hanya 1 kandidat lolos (yang overlap dibuang)
    assert len(candidates) == 1
    c = candidates[0]

    assert c.source == "ai"
    assert c.final_score == 8.8
    assert c.hook_text == "Momen Ngakak Pecah Abis"
    # Start snapped ke scene cut 9.5 (dalam 2.5s sebelum 10.0)
    assert c.start_time == 9.5
    # End snapped ke scene cut 46.0 (dalam 2.5s setelah 45.0)
    assert c.end_time == 46.0
    # Hook teaser tersimpan
    assert c.hook_moment_start == 33.0
    assert c.hook_caption == "PUNCHLINE GILA!"
    assert c.score_breakdown["source"] == "ai"
    assert c.score_breakdown["archetype"] == "funny_reaction"


def test_create_job_with_content_brief():
    """Test pembuatan job AI Discovery dengan content brief campaign."""
    mock_db = MagicMock()
    service = AIDiscoveryService(mock_db)

    video = MagicMock(id=5)
    service.video_repo.get = MagicMock(return_value=video)
    service.category_repo.get_by_name = MagicMock(return_value=None)
    service.category_repo.get_all = MagicMock(return_value=[])

    mock_job = MagicMock(id=99)
    service.job_service.create = MagicMock(return_value=mock_job)

    job_id = service.create_job(
        video_id=5,
        category_text="Gaming ShopeePay",
        scan_visual=True,
        content_brief="Wajib ada promo ShopeePay Games dan facecam streamer.",
    )

    assert job_id == 99
    assert mock_job.ai_category_text == "Gaming ShopeePay"
    assert mock_job.ai_scan_visual is True
    assert mock_job.ai_content_brief == "Wajib ada promo ShopeePay Games dan facecam streamer."

