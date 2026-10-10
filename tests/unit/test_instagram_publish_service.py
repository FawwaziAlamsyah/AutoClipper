"""Unit tests untuk InstagramPublishService (preflight, resumable upload, polling, publish, retry rules)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.exceptions.base import ValidationException
from app.core.security.token_crypto import encrypt_token
from app.models.clip_model import ClipModel
from app.models.oauth_token_model import OAuthTokenModel
from app.models.video_model import VideoModel
from app.repositories.oauth_token_repository import OAuthTokenRepository
from app.services.instagram_publish_service import (
    InstagramPublishService,
    PublishResult,
    PublishUncertainError,
)
from app.services.token_manager.setup import build_default_manager


@pytest.fixture(autouse=True)
def setup_test_crypto_key():
    """Pastikan TOKEN_ENCRYPTION_KEY terpasang untuk unit test."""
    test_key = Fernet.generate_key().decode()
    with patch.object(settings, "TOKEN_ENCRYPTION_KEY", test_key):
        yield


@pytest.fixture(autouse=True)
def clean_oauth_tokens(db_session: Session):
    """Bersihkan oauth_tokens di awal setiap test transaksi."""
    db_session.query(OAuthTokenModel).delete()
    yield


@pytest.fixture
def test_clip(db_session: Session, tmp_path: Path) -> ClipModel:
    """Fixture clip dan video dummy lengkap dengan file mp4 nyata di disk."""
    dummy_video_file = tmp_path / "valid_reel.mp4"
    dummy_video_file.write_bytes(b"dummy mp4 video content header and stream data" * 100)

    video = VideoModel(
        original_filename="sample_source.mp4",
        source_type="upload",
        file_path=str(dummy_video_file),
        status="completed",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    clip = ClipModel(
        video_id=video.id,
        file_path=str(dummy_video_file),
        start_time=0.0,
        end_time=30.0,
        aspect_ratio="9:16",
        status="completed",
    )
    db_session.add(clip)
    db_session.commit()
    db_session.refresh(clip)
    return clip


@pytest.fixture
def active_token(db_session: Session) -> OAuthTokenModel:
    """Fixture token Instagram aktif tersimpan di database."""
    now = datetime.now(timezone.utc)
    token = OAuthTokenModel(
        platform="instagram",
        account_id="17841400000000001",
        access_token_encrypted=encrypt_token("dummy-ig-access-token-123"),
        issued_at=now - timedelta(days=10),
        expires_at=now + timedelta(days=50),
        expiry_estimated=False,
        status="active",
        seed_fingerprint="dummy-fingerprint",
    )
    repo = OAuthTokenRepository(db_session)
    return repo.upsert(token)


# ── Test Preflight ────────────────────────────────────────────────────────────

def test_preflight_clip_not_found(db_session: Session):
    service = InstagramPublishService(db_session)
    report = service.preflight(clip_id=999999, caption="Test caption")
    assert report.ok is False
    assert any("tidak ditemukan di database" in err for err in report.errors)


def test_preflight_file_not_found_on_disk(db_session: Session, test_clip: ClipModel):
    test_clip.file_path = "C:/non_existent_folder/clip.mp4"
    test_clip.edited_file_path = None
    db_session.commit()

    service = InstagramPublishService(db_session)
    report = service.preflight(clip_id=test_clip.id, caption="Test caption")
    assert report.ok is False
    assert any("tidak ditemukan di disk" in err for err in report.errors)


def test_preflight_invalid_extension(db_session: Session, test_clip: ClipModel, tmp_path: Path):
    avi_file = tmp_path / "video.avi"
    avi_file.write_bytes(b"dummy avi content")
    test_clip.file_path = str(avi_file)
    db_session.commit()

    service = InstagramPublishService(db_session)
    report = service.preflight(clip_id=test_clip.id, caption="Test caption")
    assert report.ok is False
    assert any("Format file '.avi' tidak didukung" in err for err in report.errors)


def test_preflight_duration_too_short(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 2.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"):
        report = service.preflight(clip_id=test_clip.id, caption="Test caption")
        assert report.ok is False
        assert any("kurang dari batas minimum" in err for err in report.errors)


def test_preflight_duration_too_long(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 95.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"):
        report = service.preflight(clip_id=test_clip.id, caption="Test caption")
        assert report.ok is False
        assert any("melebihi batas maksimum" in err for err in report.errors)


def test_preflight_aspect_ratio_non_9_16_generates_warning_only(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel
):
    service = InstagramPublishService(db_session)
    # Video horizontal 16:9 (1920x1080)
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 30.0, "width": 1920, "height": 1080}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(service, "_check_quota", return_value=(True, None)):
        report = service.preflight(clip_id=test_clip.id, caption="Test caption #fyp")
        assert report.ok is True
        assert len(report.errors) == 0
        assert len(report.warnings) == 1
        assert "Video akan dimasukkan ke bingkai 9:16" in report.warnings[0]
        assert report.will_reframe is True
        assert report.fit_mode == "pad"


def test_preflight_caption_too_long(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)
    long_caption = "A" * 2205
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 30.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_CAPTION_MAX_CHARS", 2200):
        report = service.preflight(clip_id=test_clip.id, caption=long_caption)
        assert report.ok is False
        assert any("Panjang caption" in err for err in report.errors)


def test_preflight_too_many_hashtags(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)
    many_hashtags = "Caption with tags " + " ".join(f"#tag{i}" for i in range(35))
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 30.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_CAPTION_MAX_HASHTAGS", 30):
        report = service.preflight(clip_id=test_clip.id, caption=many_hashtags)
        assert report.ok is False
        assert any("Jumlah hashtag" in err for err in report.errors)


def test_preflight_token_needs_reconnect(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    active_token.status = "needs_reconnect"
    db_session.commit()

    service = InstagramPublishService(db_session)
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 30.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"):
        report = service.preflight(clip_id=test_clip.id, caption="Test caption")
        assert report.ok is False
        assert any("Kredensial token Instagram tidak valid" in err for err in report.errors)


def test_preflight_quota_exhausted(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)
    mock_quota_resp = MagicMock()
    mock_quota_resp.status_code = 200
    mock_quota_resp.json.return_value = {
        "data": [{"quota_usage": 25, "config": {"quota_total": 25, "quota_duration": 86400}}]
    }

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 30.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch("httpx.get", return_value=mock_quota_resp):
        report = service.preflight(clip_id=test_clip.id, caption="Test caption")
        assert report.ok is False
        assert any("Kuota publikasi harian Instagram telah habis" in err for err in report.errors)


def test_preflight_quota_failure_is_non_blocking(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 30.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch("httpx.get", side_effect=httpx.ConnectError("Network error")):
        report = service.preflight(clip_id=test_clip.id, caption="Test caption")
        assert report.ok is True
        assert len(report.errors) == 0


# ── Test Publish Full Flow & Error Handling ───────────────────────────────────

def test_publish_reel_full_success_flow(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)
    progress_calls = []

    def on_progress(stage: str, pct: int):
        progress_calls.append((stage, pct))

    # Mock responses
    # 1. Quota preflight: 200
    quota_resp = MagicMock(status_code=200)
    quota_resp.json.return_value = {"data": [{"quota_usage": 5, "config": {"quota_total": 25}}]}

    # 2. Container creation: 200
    container_resp = MagicMock(status_code=200)
    container_resp.json.return_value = {"id": "c_999", "uri": "https://rupload.facebook.com/ig-cache/c_999"}

    # 3. Resumable upload: 200
    upload_resp = MagicMock(status_code=200)
    upload_resp.headers = {"content-type": "application/json"}
    upload_resp.json.return_value = {"success": True}

    # 4. Polling container: call 1 IN_PROGRESS, call 2 FINISHED
    poll_1 = MagicMock(status_code=200)
    poll_1.json.return_value = {"status_code": "IN_PROGRESS"}
    poll_2 = MagicMock(status_code=200)
    poll_2.json.return_value = {"status_code": "FINISHED"}

    # 5. Media publish: 200
    publish_resp = MagicMock(status_code=200)
    publish_resp.json.return_value = {"id": "media_777"}

    # 6. Permalink: 200
    permalink_resp = MagicMock(status_code=200)
    permalink_resp.json.return_value = {"permalink": "https://www.instagram.com/reel/Cxxxxxx/"}

    def fake_get(url, *args, **kwargs):
        if "content_publishing_limit" in url:
            return quota_resp
        if "c_999" in url:
            fake_get.poll_count += 1
            return poll_1 if fake_get.poll_count == 1 else poll_2
        if "media_777" in url:
            return permalink_resp
        return MagicMock(status_code=404)

    fake_get.poll_count = 0

    def fake_post(url, *args, **kwargs):
        if "media_publish" in url:
            return publish_resp
        if "media" in url:
            return container_resp
        if "rupload.facebook.com" in url:
            return upload_resp
        return MagicMock(status_code=404)

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 25.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_PROCESS_POLL_SECONDS", 0.01), \
         patch("httpx.get", side_effect=fake_get), \
         patch("httpx.post", side_effect=fake_post):
        res = service.publish_reel(
            clip_id=test_clip.id,
            caption="Keren banget #viral",
            share_to_feed=True,
            on_progress=on_progress,
        )

        assert isinstance(res, PublishResult)
        assert res.container_id == "c_999"
        assert res.media_id == "media_777"
        assert res.permalink == "https://www.instagram.com/reel/Cxxxxxx/"

        stages = [s for s, _ in progress_calls]
        assert "uploading" in stages
        assert "processing" in stages
        assert "publishing" in stages
        assert progress_calls[-1] == ("publishing", 100)


def test_publish_reel_poll_error_status(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)

    container_resp = MagicMock(status_code=200)
    container_resp.json.return_value = {"id": "c_error_1", "uri": "https://rupload.facebook.com/c_error_1"}

    upload_resp = MagicMock(status_code=200)
    upload_resp.headers = {"content-type": "application/json"}
    upload_resp.json.return_value = {}

    poll_error = MagicMock(status_code=200)
    poll_error.json.return_value = {"status_code": "ERROR"}

    def fake_get(url, *args, **kwargs):
        if "content_publishing_limit" in url:
            return MagicMock(status_code=200, json=lambda: {"data": []})
        return poll_error

    def fake_post(url, *args, **kwargs):
        if "media" in url:
            return container_resp
        return upload_resp

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 15.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_PROCESS_POLL_SECONDS", 0.01), \
         patch("httpx.get", side_effect=fake_get), \
         patch("httpx.post", side_effect=fake_post):
        with pytest.raises(ValidationException, match="status: ERROR"):
            service.publish_reel(clip_id=test_clip.id, caption="Tes error")


def test_publish_reel_poll_timeout(db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel):
    service = InstagramPublishService(db_session)

    container_resp = MagicMock(status_code=200)
    container_resp.json.return_value = {"id": "c_timeout_1", "uri": "https://rupload.facebook.com/c_timeout_1"}

    upload_resp = MagicMock(status_code=200)
    upload_resp.headers = {}

    poll_in_progress = MagicMock(status_code=200)
    poll_in_progress.json.return_value = {"status_code": "IN_PROGRESS"}

    def fake_get(url, *args, **kwargs):
        if "content_publishing_limit" in url:
            return MagicMock(status_code=200, json=lambda: {"data": []})
        return poll_in_progress

    def fake_post(url, *args, **kwargs):
        if "media" in url:
            return container_resp
        return upload_resp

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 15.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(settings, "IG_PROCESS_POLL_SECONDS", 0.01), \
         patch.object(settings, "IG_PROCESS_TIMEOUT_SECONDS", 0.05), \
         patch("httpx.get", side_effect=fake_get), \
         patch("httpx.post", side_effect=fake_post):
        with pytest.raises(ValidationException, match="melebihi batas waktu"):
            service.publish_reel(clip_id=test_clip.id, caption="Tes timeout")


def test_publish_reel_code_190_marks_needs_reconnect(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel
):
    service = InstagramPublishService(db_session)

    # Saat membuat container, Graph API mengembalikan code 190
    error_190_resp = MagicMock(status_code=400)
    error_190_resp.json.return_value = {
        "error": {
            "message": "Error validating access token: Session has expired.",
            "type": "OAuthException",
            "code": 190,
        }
    }

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 20.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(service, "_check_quota", return_value=(True, None)), \
         patch("httpx.post", return_value=error_190_resp):
        with pytest.raises(ValidationException, match="tidak valid atau telah kedaluwarsa"):
            service.publish_reel(clip_id=test_clip.id, caption="Tes code 190")

        # Pastikan token di DB sekarang ditandai needs_reconnect
        db_session.refresh(active_token)
        assert active_token.status == "needs_reconnect"


def test_publish_reel_media_publish_timeout_raises_uncertain_error_no_retry(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel
):
    service = InstagramPublishService(db_session)

    container_resp = MagicMock(status_code=200)
    container_resp.json.return_value = {"id": "c_uncertain", "uri": "https://rupload.facebook.com/c_uncertain"}

    upload_resp = MagicMock(status_code=200)
    upload_resp.headers = {}

    poll_finished = MagicMock(status_code=200)
    poll_finished.json.return_value = {"status_code": "FINISHED"}

    post_call_count = {"publish": 0}

    def fake_post(url, *args, **kwargs):
        if "media_publish" in url:
            post_call_count["publish"] += 1
            raise httpx.ReadTimeout("Timeout waiting for media_publish response")
        if "media" in url:
            return container_resp
        return upload_resp

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 20.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(service, "_check_quota", return_value=(True, None)), \
         patch("httpx.get", return_value=poll_finished), \
         patch("httpx.post", side_effect=fake_post):
        with pytest.raises(PublishUncertainError, match="Status publish tidak pasti"):
            service.publish_reel(clip_id=test_clip.id, caption="Tes timeout publish")

        # Harus dipastikan media_publish TIDAK DI-RETRY (hanya 1 kali panggil)
        assert post_call_count["publish"] == 1


def test_publish_reel_media_publish_500_raises_uncertain_error_no_retry(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel
):
    service = InstagramPublishService(db_session)

    container_resp = MagicMock(status_code=200)
    container_resp.json.return_value = {"id": "c_500", "uri": "https://rupload.facebook.com/c_500"}

    upload_resp = MagicMock(status_code=200)
    upload_resp.headers = {}

    poll_finished = MagicMock(status_code=200)
    poll_finished.json.return_value = {"status_code": "FINISHED"}

    post_call_count = {"publish": 0}

    def fake_post(url, *args, **kwargs):
        if "media_publish" in url:
            post_call_count["publish"] += 1
            return MagicMock(status_code=500, json=lambda: {"error": "Server error"})
        if "media" in url:
            return container_resp
        return upload_resp

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 20.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(service, "_check_quota", return_value=(True, None)), \
         patch("httpx.get", return_value=poll_finished), \
         patch("httpx.post", side_effect=fake_post):
        with pytest.raises(PublishUncertainError, match="Status publish tidak pasti"):
            service.publish_reel(clip_id=test_clip.id, caption="Tes 500 publish")

        assert post_call_count["publish"] == 1


def test_publish_reel_permalink_failure_does_not_abort_success(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel
):
    service = InstagramPublishService(db_session)

    container_resp = MagicMock(status_code=200)
    container_resp.json.return_value = {"id": "c_no_link", "uri": "https://rupload.facebook.com/c_no_link"}

    upload_resp = MagicMock(status_code=200)
    upload_resp.headers = {}

    poll_finished = MagicMock(status_code=200)
    poll_finished.json.return_value = {"status_code": "FINISHED"}

    publish_resp = MagicMock(status_code=200)
    publish_resp.json.return_value = {"id": "media_success_no_link"}

    def fake_get(url, *args, **kwargs):
        if "content_publishing_limit" in url:
            return MagicMock(status_code=200, json=lambda: {"data": []})
        if "c_no_link" in url:
            return poll_finished
        if "media_success_no_link" in url:
            # Gagal mengambil permalink (HTTP 404 / error)
            return MagicMock(status_code=404)
        return MagicMock(status_code=404)

    def fake_post(url, *args, **kwargs):
        if "media_publish" in url:
            return publish_resp
        if "media" in url:
            return container_resp
        return upload_resp

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 20.0, "width": 1080, "height": 1920}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch("httpx.get", side_effect=fake_get), \
         patch("httpx.post", side_effect=fake_post):
        res = service.publish_reel(clip_id=test_clip.id, caption="Tanpa permalink")
        assert res.media_id == "media_success_no_link"
        assert res.permalink is None


def test_publish_reel_cleans_up_temp_prepared_video_on_success(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel, tmp_path: Path
):
    service = InstagramPublishService(db_session)
    temp_video = tmp_path / "temp_reframe.mp4"
    temp_video.write_bytes(b"dummy reframed video bytes")

    from app.services.instagram_video_prep_service import PreparedVideo
    mock_prep = PreparedVideo(path=temp_video, is_temp=True, reframed=True, width=1080, height=1920)

    # Responses
    container_resp = MagicMock(status_code=200, json=lambda: {"id": "c_cleanup_ok", "uri": "https://rupload.facebook.com/ig/c"})
    upload_resp = MagicMock(status_code=200, headers={}, json=lambda: {"success": True})
    poll_finished = MagicMock(status_code=200, json=lambda: {"status_code": "FINISHED"})
    publish_resp = MagicMock(status_code=200, json=lambda: {"id": "media_cleanup_ok"})
    permalink_resp = MagicMock(status_code=200, json=lambda: {"permalink": "https://instagram.com/reel/123"})

    cleanup_called = False

    def fake_cleanup(p):
        nonlocal cleanup_called
        cleanup_called = True

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 20.0, "width": 1920, "height": 1080}), \
         patch.object(service.video_prep_service, "prepare", return_value=mock_prep), \
         patch.object(service.video_prep_service, "cleanup", side_effect=fake_cleanup), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch("httpx.get", side_effect=lambda url, *a, **k: permalink_resp if "media_cleanup_ok" in url else (poll_finished if "c_cleanup_ok" in url else MagicMock(status_code=200, json=lambda: {"data": []}))), \
         patch("httpx.post", side_effect=lambda url, *a, **k: publish_resp if "media_publish" in url else (container_resp if "media" in url else upload_resp)):
        res = service.publish_reel(clip_id=test_clip.id, caption="Clean me", fit_mode="pad")
        assert res.media_id == "media_cleanup_ok"
        assert cleanup_called is True


def test_publish_reel_cleans_up_temp_prepared_video_on_error(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel, tmp_path: Path
):
    service = InstagramPublishService(db_session)
    temp_video = tmp_path / "temp_reframe_err.mp4"
    temp_video.write_bytes(b"dummy bytes")

    from app.services.instagram_video_prep_service import PreparedVideo
    mock_prep = PreparedVideo(path=temp_video, is_temp=True, reframed=True, width=1080, height=1920)

    # Container creation error (HTTP 400)
    err_resp = MagicMock(status_code=400, headers={}, json=lambda: {"error": {"message": "Invalid video aspect ratio", "code": 100}})

    cleanup_called = False

    def fake_cleanup(p):
        nonlocal cleanup_called
        cleanup_called = True

    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 20.0, "width": 1920, "height": 1080}), \
         patch.object(service.video_prep_service, "prepare", return_value=mock_prep), \
         patch.object(service.video_prep_service, "cleanup", side_effect=fake_cleanup), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch("httpx.get", return_value=MagicMock(status_code=200, json=lambda: {"data": []})), \
         patch("httpx.post", return_value=err_resp):
        with pytest.raises(ValidationException):
            service.publish_reel(clip_id=test_clip.id, caption="Fail me", fit_mode="pad")
        assert cleanup_called is True


def test_preflight_fit_mode_off_warns_and_does_not_reframe(
    db_session: Session, test_clip: ClipModel, active_token: OAuthTokenModel
):
    service = InstagramPublishService(db_session)
    # 16:9 horizontal video
    with patch.object(service.ffmpeg_service, "extract_metadata", return_value={"duration_seconds": 30.0, "width": 1920, "height": 1080}), \
         patch.object(settings, "IG_USER_ID", "17841400000000001"), \
         patch.object(service, "_check_quota", return_value=(True, None)):
        report = service.preflight(clip_id=test_clip.id, caption="Caption", fit_mode="off")
        assert report.ok is True
        assert report.will_reframe is False
        assert report.fit_mode == "off"
        assert any("Reframing dinonaktifkan" in w for w in report.warnings)

