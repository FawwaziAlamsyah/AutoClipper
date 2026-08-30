"""Tests for the video download logic using yt-dlp."""

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import yt_dlp
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.download_service import DownloadService
from app.models.video_model import VideoModel


@patch("yt_dlp.YoutubeDL")
def test_download_service_success(mock_ytdl: MagicMock, db_session: Session) -> None:
    """DownloadService should successfully parse yt-dlp info and create DB record."""
    # Setup mocks
    instance = mock_ytdl.return_value.__enter__.return_value
    instance.extract_info.return_value = {
        "title": "Mock Video YouTube",
        "duration": 120.0,
        "ext": "mp4",
    }

    # Buat file mock agar file_path.exists() mengembalikan True
    file_path_mock = "mock_file.mp4"
    instance.prepare_filename.return_value = file_path_mock

    with patch("pathlib.Path.exists", return_value=True), \
        patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 1024 * 1024

        service = DownloadService(db_session)
        video = service.download_video("https://www.youtube.com/watch?v=mock")

        assert video.id is not None
        assert video.original_filename == "Mock Video YouTube.mp4"
        assert video.source_type == "download"
        assert video.source_url == "https://www.youtube.com/watch?v=mock"
        assert video.duration_seconds == 120.0
        assert video.file_size_bytes == 1024 * 1024
        assert video.status == "uploaded"
        mock_ytdl.assert_called()
        ydl_opts = mock_ytdl.call_args.args[0]
        # Format wajib minimal 720p & cap 1080p (client kualitas baik).
        assert "height>=720" in ydl_opts["format"]
        assert "height<=1080" in ydl_opts["format"]


@patch("app.services.download_service.DownloadService._extract_and_register")
def test_download_strategy_order_no_cookies(mock_extract: MagicMock, db_session: Session) -> None:
    """download_video() tanpa cookies: tv/tv_simply/ios/web dulu, android terakhir."""
    mock_extract.side_effect = yt_dlp.utils.DownloadError("boom")
    service = DownloadService(db_session)

    try:
        service.download_video("https://www.youtube.com/watch?v=mock")
    except Exception:
        pass

    assert mock_extract.call_count >= 2
    first_opts = mock_extract.call_args_list[0].args[1]
    last_opts = mock_extract.call_args_list[-1].args[1]
    # Client pertama = tv (bukan android), format wajib minimal 720p.
    assert first_opts.get("extractor_args", {}).get("youtube", {}).get("player_client") == ["tv"]
    assert "height>=720" in first_opts["format"]
    # Attempt terakhir = android fallback, TANPA minimum height.
    assert last_opts.get("extractor_args", {}).get("youtube", {}).get("player_client") == ["android"]
    assert "height>=720" not in last_opts["format"]


@patch("app.services.download_service.DownloadService._extract_and_register")
def test_download_strategy_android_fallback_logs_warning(mock_extract: MagicMock, db_session: Session) -> None:
    """Kalau cuma android yang berhasil, muncul warning resolusi rendah di log."""
    calls = iter([yt_dlp.utils.DownloadError("boom"), yt_dlp.utils.DownloadError("boom"),
                  yt_dlp.utils.DownloadError("boom"), yt_dlp.utils.DownloadError("boom"),
                  "android-result"])

    def _fake(*a, **k):
        # Fungsi side_effect yang me-raise DownloadError (bukan sekadar return)
        # supaya mock benar-benar melemparnya seperti yt-dlp asli.
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    mock_extract.side_effect = _fake
    service = DownloadService(db_session)

    with patch("app.services.download_service.logger.warning") as mock_warn:
        result = service.download_video("https://www.youtube.com/watch?v=mock")

    assert result == "android-result"
    # Proses balik ke android → warning soal resolusi mungkin rendah.
    assert any("client android" in str(a) for a in (c.args for c in mock_warn.call_args_list))


@patch("app.services.download_service._abort_thread")
@patch("yt_dlp.YoutubeDL")
def test_download_hang_detected_and_aborts(mock_ytdl: MagicMock, mock_abort: MagicMock, db_session: Session) -> None:
    """Download yang diam tanpa progress (hang) harus terdeteksi watchdog & di-abort
    supaya chain lanjut ke strategi berikut, bukan ngestuck selamanya."""
    import time as _time

    def _slow_extract(*a, **k):
        _time.sleep(2)  # simulasi stream freeze — blocking singkat, tanpa progress
        return {"title": "x", "ext": "mp4"}

    instance = mock_ytdl.return_value.__enter__.return_value
    instance.extract_info.side_effect = _slow_extract

    service = DownloadService(db_session)
    with patch("app.services.download_service.HANG_TIMEOUT_SEC", 0.2), \
         patch("app.services.download_service.ABORT_GRACE_SEC", 0.1):
        try:
            service.download_video("https://www.youtube.com/watch?v=mock")
        except Exception:
            pass

    # Watchdog harus memicu abort (hang terdeteksi setelah timeout kecil).
    mock_abort.assert_called()


def test_api_download_endpoint_mocked(client: TestClient) -> None:
    """POST /upload/download should start download and return download_id."""
    with patch(
        "app.services.download_service.DownloadService.start_download",
        return_value={"download_id": "dl_abc123", "status": "downloading"},
    ) as mock_dl:
        response = client.post("/upload/download", json={"url": "https://test.com"})

        assert response.status_code == 200
        res_json = response.json()
        assert res_json["download_id"] == "dl_abc123"
        assert res_json["status"] == "downloading"
        mock_dl.assert_called_once_with("https://test.com")


def test_api_download_progress_endpoint(client: TestClient) -> None:
    """GET /upload/download/{id} should return progress percent."""
    with patch(
        "app.services.download_service.DownloadService.get_download_progress",
        return_value={"percent": 55, "status": "downloading", "video": None, "error": None},
    ):
        response = client.get("/upload/download/dl_abc123")

        assert response.status_code == 200
        res_json = response.json()
        assert res_json["percent"] == 55
        assert res_json["status"] == "downloading"
