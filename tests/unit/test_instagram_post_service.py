"""Unit tests untuk InstagramPostService, orkestrasi background, riwayat DB, dan router /instagram/*."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.core.security.token_crypto import encrypt_token
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.clip_model import ClipModel
from app.models.instagram_post_model import InstagramPostModel
from app.models.oauth_token_model import OAuthTokenModel
from app.models.video_model import VideoModel
from app.repositories.clip_repository import ClipRepository
from app.repositories.instagram_post_repository import InstagramPostRepository
from app.repositories.oauth_token_repository import OAuthTokenRepository
from app.services.instagram_post_service import (
    _IG_PUBLISHES,
    InstagramPostService,
)
from app.services.instagram_publish_service import (
    InstagramPublishService,
    PreflightReport,
    PublishResult,
    PublishUncertainError,
)


@pytest.fixture(autouse=True)
def setup_test_crypto_key():
    """Pastikan TOKEN_ENCRYPTION_KEY terpasang untuk unit test."""
    test_key = Fernet.generate_key().decode()
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", test_key):
        yield


@pytest.fixture(autouse=True)
def clean_test_tables(db_session: Session):
    """Bersihkan data tabel instagram_posts dan oauth_tokens di setiap test."""
    db_session.query(InstagramPostModel).delete()
    db_session.query(OAuthTokenModel).delete()
    _IG_PUBLISHES.clear()
    yield


@pytest.fixture
def sample_clip(db_session: Session, tmp_path: Path) -> ClipModel:
    """Fixture clip dan video dummy."""
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"dummy video bytes" * 50)

    video = VideoModel(
        original_filename="source.mp4",
        source_type="upload",
        file_path=str(video_file),
        status="completed",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    clip = ClipModel(
        video_id=video.id,
        file_path=str(video_file),
        start_time=0.0,
        end_time=30.0,
        aspect_ratio="9:16",
        status="completed",
        instagram_published=False,
    )
    db_session.add(clip)
    db_session.commit()
    db_session.refresh(clip)
    return clip


# ── Test start_publish Validations ───────────────────────────────────────────

def test_start_publish_duplicate_active_rejected(db_session: Session, sample_clip: ClipModel):
    # Buat post aktif
    post_repo = InstagramPostRepository(db_session)
    active_post = InstagramPostModel(
        clip_id=sample_clip.id,
        caption="Post sedang jalan",
        status="uploading",
    )
    post_repo.save(active_post)

    service = InstagramPostService(db_session)
    with pytest.raises(ValidationException, match="sedang dalam proses publikasi"):
        service.start_publish(clip_id=sample_clip.id, caption="Post kedua")


def test_start_publish_repost_without_confirm_rejected(db_session: Session, sample_clip: ClipModel):
    sample_clip.instagram_published = True
    db_session.commit()

    service = InstagramPostService(db_session)
    with pytest.raises(ValidationException, match="sudah pernah dikirim ke Instagram"):
        service.start_publish(clip_id=sample_clip.id, caption="Repost", confirm_repost=False)


def test_start_publish_preflight_failure_synchronously_raises(db_session: Session, sample_clip: ClipModel):
    mock_publish_svc = MagicMock()
    mock_publish_svc.preflight.return_value = PreflightReport(
        ok=False,
        errors=["Durasi video melebihi batas maksimum Instagram Reels (90.0s)."],
        warnings=[],
        duration_seconds=95.0,
    )

    service = InstagramPostService(db_session, publish_service=mock_publish_svc)
    with pytest.raises(ValidationException, match="Durasi video melebihi batas"):
        service.start_publish(clip_id=sample_clip.id, caption="Caption panjang")

    post_repo = InstagramPostRepository(db_session)
    assert post_repo.list_for_clip(sample_clip.id) == []


@pytest.fixture
def session_factory(db_session: Session):
    """Factory pembuat session yang menggunakan koneksi transaksi yang sama."""
    return lambda: SessionLocal(bind=db_session.connection())


# ── Test Background Publish Orchestration ────────────────────────────────────

def test_start_publish_success_flow(db_session: Session, sample_clip: ClipModel, session_factory):
    mock_publish_svc = MagicMock()
    mock_publish_svc.preflight.return_value = PreflightReport(
        ok=True, errors=[], warnings=[], duration_seconds=30.0
    )

    def fake_publish_reel(clip_id, caption, share_to_feed=True, fit_mode=None, on_progress=None):
        if on_progress:
            on_progress("uploading", 30)
            on_progress("processing", 70)
        return PublishResult(
            container_id="c_success_1",
            media_id="m_success_1",
            permalink="https://www.instagram.com/reel/Cxxxx1/",
        )

    service = InstagramPostService(db_session, publish_service=mock_publish_svc, session_factory=session_factory)

    with patch.object(InstagramPublishService, "publish_reel", side_effect=fake_publish_reel):
        local_id = service.start_publish(
            clip_id=sample_clip.id,
            caption="Keren banget #fyp",
            share_to_feed=True,
            confirm_repost=False,
        )

        assert local_id.startswith("ig_")

        # Tunggu thread selesai (maksimal 2 detik)
        for _ in range(20):
            prog = service.get_progress(local_id)
            if prog.get("status") == "published":
                break
            time.sleep(0.05)

        prog = service.get_progress(local_id)
        assert prog["status"] == "published"
        assert prog["progress"] == 100
        assert prog["permalink"] == "https://www.instagram.com/reel/Cxxxx1/"

        # Cek DB record
        db_session.expire_all()
        post_repo = InstagramPostRepository(db_session)
        post = post_repo.latest_for_clip(sample_clip.id)
        assert post is not None
        assert post.status == "published"
        assert post.media_id == "m_success_1"
        assert post.permalink == "https://www.instagram.com/reel/Cxxxx1/"
        assert post.published_at is not None

        # Cek flag di clip
        clip_repo = ClipRepository(db_session)
        c = clip_repo.get(sample_clip.id)
        assert c.instagram_published is True


def test_start_publish_uncertain_error_leaves_clip_flag_false(
    db_session: Session, sample_clip: ClipModel, session_factory
):
    mock_publish_svc = MagicMock()
    mock_publish_svc.preflight.return_value = PreflightReport(
        ok=True, errors=[], warnings=[], duration_seconds=30.0
    )

    def fake_publish_uncertain(clip_id, caption, share_to_feed=True, fit_mode=None, on_progress=None):
        raise PublishUncertainError("Status publish tidak pasti — timeout")

    service = InstagramPostService(db_session, publish_service=mock_publish_svc, session_factory=session_factory)

    with patch.object(InstagramPublishService, "publish_reel", side_effect=fake_publish_uncertain):
        local_id = service.start_publish(clip_id=sample_clip.id, caption="Uncertain")

        for _ in range(20):
            prog = service.get_progress(local_id)
            if prog.get("status") == "unknown":
                break
            time.sleep(0.05)

        prog = service.get_progress(local_id)
        assert prog["status"] == "unknown"
        assert "tidak pasti" in prog.get("error", "")

        db_session.expire_all()
        post_repo = InstagramPostRepository(db_session)
        post = post_repo.latest_for_clip(sample_clip.id)
        assert post.status == "unknown"

        clip_repo = ClipRepository(db_session)
        c = clip_repo.get(sample_clip.id)
        assert c.instagram_published is False  # Wajib tetap False!


def test_start_publish_general_exception_marks_failed(
    db_session: Session, sample_clip: ClipModel, session_factory
):
    mock_publish_svc = MagicMock()
    mock_publish_svc.preflight.return_value = PreflightReport(
        ok=True, errors=[], warnings=[], duration_seconds=30.0
    )

    def fake_publish_fail(clip_id, caption, share_to_feed=True, fit_mode=None, on_progress=None):
        raise ValidationException("File video corrupt")

    service = InstagramPostService(db_session, publish_service=mock_publish_svc, session_factory=session_factory)

    with patch.object(InstagramPublishService, "publish_reel", side_effect=fake_publish_fail):
        local_id = service.start_publish(clip_id=sample_clip.id, caption="Fail")

        for _ in range(20):
            prog = service.get_progress(local_id)
            if prog.get("status") == "failed":
                break
            time.sleep(0.05)

        prog = service.get_progress(local_id)
        assert prog["status"] == "failed"

        db_session.expire_all()
        post_repo = InstagramPostRepository(db_session)
        post = post_repo.latest_for_clip(sample_clip.id)
        assert post.status == "failed"
        assert "File video corrupt" in post.error_message

        clip_repo = ClipRepository(db_session)
        c = clip_repo.get(sample_clip.id)
        assert c.instagram_published is False


def test_mark_stale_failed(db_session: Session, sample_clip: ClipModel):
    post_repo = InstagramPostRepository(db_session)
    p1 = post_repo.save(InstagramPostModel(clip_id=sample_clip.id, caption="p1", status="uploading"))
    p2 = post_repo.save(InstagramPostModel(clip_id=sample_clip.id, caption="p2", status="processing"))
    p3 = post_repo.save(InstagramPostModel(clip_id=sample_clip.id, caption="p3", status="published"))
    p4 = post_repo.save(InstagramPostModel(clip_id=sample_clip.id, caption="p4", status="failed"))

    service = InstagramPostService(db_session)
    recovered = service.mark_stale_failed()
    assert recovered == 2

    db_session.expire_all()
    assert post_repo.get(p1.id).status == "failed"
    assert "aplikasi restart" in post_repo.get(p1.id).error_message
    assert post_repo.get(p2.id).status == "failed"
    assert post_repo.get(p3.id).status == "published"
    assert post_repo.get(p4.id).status == "failed"


# ── Test Router /instagram/* ──────────────────────────────────────────────────

def test_api_instagram_status(db_session: Session):
    token_repo = OAuthTokenRepository(db_session)
    now = datetime.now(timezone.utc)
    token_repo.upsert(
        OAuthTokenModel(
            platform="instagram",
            account_id="17841400000000001",
            access_token_encrypted=encrypt_token("dummy-secret-token"),
            issued_at=now,
            expires_at=now + timedelta(days=50),
            expiry_estimated=False,
            status="active",
        )
    )

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with patch.object(settings, "IG_USER_ID", "17841400000000001"), \
             patch.object(settings, "IG_ACCESS_TOKEN", "dummy-secret-token"):
            client = TestClient(app)
            resp = client.get("/instagram/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["configured"] is True
            assert data["connected"] is True
            assert data["status"] == "active"
            assert data["username"] == "17841400000000001"
            assert data["days_left"] > 45
            # Pastikan tidak ada token mentah di response
            assert "dummy-secret-token" not in resp.text
            assert "access_token" not in data
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_api_instagram_publish_and_status(db_session: Session, sample_clip: ClipModel):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with patch.object(InstagramPublishService, "preflight", return_value=PreflightReport(ok=True, errors=[], warnings=[], duration_seconds=20.0)), \
             patch.object(InstagramPublishService, "publish_reel", return_value=PublishResult(container_id="c_1", media_id="m_1", permalink="https://ig/1")):
            client = TestClient(app)

            # 1. POST /instagram/publish/{clip_id}
            resp_post = client.post(
                f"/instagram/publish/{sample_clip.id}",
                json={"caption": "Test API #reels", "share_to_feed": True, "confirm_repost": False},
            )
            assert resp_post.status_code == 200
            post_data = resp_post.json()
            assert "local_id" in post_data
            local_id = post_data["local_id"]

            # 2. GET /instagram/publish/{local_id}/status
            resp_status = client.get(f"/instagram/publish/{local_id}/status")
            assert resp_status.status_code == 200
            status_data = resp_status.json()
            assert "status" in status_data
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_api_instagram_preflight(db_session: Session, sample_clip: ClipModel):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with patch.object(
            InstagramPublishService,
            "preflight",
            return_value=PreflightReport(ok=True, errors=[], warnings=["Rasio non-9:16"], duration_seconds=45.0),
        ):
            client = TestClient(app)
            resp = client.get(f"/instagram/preflight/{sample_clip.id}?caption=halo")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["duration_seconds"] == 45.0
            assert "Rasio non-9:16" in data["warnings"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_api_instagram_posts_history(db_session: Session, sample_clip: ClipModel):
    post_repo = InstagramPostRepository(db_session)
    post_repo.save(
        InstagramPostModel(
            clip_id=sample_clip.id,
            caption="Histori 1",
            status="published",
            permalink="https://ig/hist1",
        )
    )

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        resp = client.get(f"/instagram/posts/{sample_clip.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "published"
        assert data[0]["permalink"] == "https://ig/hist1"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_start_publish_forwards_fit_mode(
    db_session: Session, sample_clip: ClipModel, session_factory
):
    mock_publish_svc = MagicMock()
    mock_publish_svc.preflight.return_value = PreflightReport(
        ok=True, errors=[], warnings=[], duration_seconds=30.0, will_reframe=True, fit_mode="blur"
    )

    received_fit_mode = None

    def fake_publish(clip_id, caption, share_to_feed=True, fit_mode=None, on_progress=None):
        nonlocal received_fit_mode
        received_fit_mode = fit_mode
        return PublishResult(container_id="c_1", media_id="m_1", permalink="https://ig/1")

    service = InstagramPostService(db_session, publish_service=mock_publish_svc, session_factory=session_factory)

    with patch.object(InstagramPublishService, "publish_reel", side_effect=fake_publish):
        local_id = service.start_publish(
            clip_id=sample_clip.id,
            caption="Test fit blur",
            fit_mode="blur",
        )
        mock_publish_svc.preflight.assert_called_once_with(sample_clip.id, "Test fit blur", fit_mode="blur")

        for _ in range(20):
            prog = service.get_progress(local_id)
            if prog.get("status") == "published":
                break
            time.sleep(0.05)

        assert received_fit_mode == "blur"


def test_api_instagram_preflight_with_fit_mode(db_session: Session, sample_clip: ClipModel):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with patch.object(
            InstagramPublishService,
            "preflight",
            return_value=PreflightReport(
                ok=True,
                errors=[],
                warnings=["Video akan dimasukkan ke bingkai 9:16 (mode: blur)"],
                duration_seconds=45.0,
                will_reframe=True,
                fit_mode="blur",
            ),
        ) as mock_preflight:
            client = TestClient(app)
            resp = client.get(f"/instagram/preflight/{sample_clip.id}?caption=halo&fit_mode=blur")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["will_reframe"] is True
            assert data["fit_mode"] == "blur"
            mock_preflight.assert_called_once_with(clip_id=sample_clip.id, caption="halo", fit_mode="blur")
    finally:
        app.dependency_overrides.pop(get_db, None)

