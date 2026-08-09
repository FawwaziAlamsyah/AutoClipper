"""Tests for the video download logic using yt-dlp."""

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch
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
