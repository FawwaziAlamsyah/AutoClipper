"""Unit test untuk verifikasi flag instagram_published di candidate dict dan template."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.core.config.settings import settings
from app.db.session import get_db
from app.main import app
from app.models.candidate_model import CandidateModel
from app.models.clip_model import ClipModel
from app.models.job_model import JobModel
from app.models.video_model import VideoModel


@pytest.fixture(autouse=True)
def setup_test_crypto_key():
    test_key = Fernet.generate_key().decode()
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", test_key):
        yield


def test_candidate_dict_includes_instagram_published(db_session: Session, tmp_path: Path):
    video_file = tmp_path / "test.mp4"
    video_file.write_bytes(b"content")

    video = VideoModel(
        original_filename="vid.mp4",
        source_type="upload",
        file_path=str(video_file),
        status="completed",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    job = JobModel(
        video_id=video.id,
        job_type="process",
        pipeline_name="default",
        status="completed",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    candidate = CandidateModel(
        video_id=video.id,
        job_id=job.id,
        start_time=10.0,
        end_time=25.0,
        final_score=85.0,
        status="selected",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    clip = ClipModel(
        candidate_id=candidate.id,
        video_id=video.id,
        file_path=str(video_file),
        start_time=10.0,
        end_time=25.0,
        aspect_ratio="9:16",
        status="completed",
        instagram_published=True,
    )
    db_session.add(clip)
    db_session.commit()
    db_session.refresh(clip)

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)

        # 1. Test kandidat list halaman video
        resp = client.get(f"/candidates/video/{video.id}")
        assert resp.status_code == 200
        assert "Instagram ✓" in resp.text

        # 2. Test halaman detail kandidat
        resp_detail = client.get(f"/candidates/{candidate.id}")
        assert resp_detail.status_code == 200
        assert "instagramPublishCard" in resp_detail.text
        assert "igCaption" in resp_detail.text
    finally:
        app.dependency_overrides.pop(get_db, None)
