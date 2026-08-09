"""Tests for the video upload logic and endpoints."""

import io
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.video_service import VideoService
from app.core.exceptions.base import ValidationException


def test_video_service_upload_success(db_session: Session) -> None:
    """VideoService should successfully save a valid video."""
    service = VideoService(db_session)
    file_content = b"fake video content mp4"
    
    video = service.upload("test_video.mp4", file_content)
    
    assert video.id is not None
    assert video.original_filename == "test_video.mp4"
    assert video.status == "uploaded"
    assert video.file_size_bytes == len(file_content)
    
    # Cleanup file
    service.delete(video.id)


def test_video_service_invalid_extension(db_session: Session) -> None:
    """VideoService should reject unsupported video extensions."""
    service = VideoService(db_session)
    
    try:
        service.upload("test_video.txt", b"some text")
        assert False, "Should have raised ValidationException"
    except ValidationException as e:
        assert "tidak didukung" in str(e)


def test_api_upload_endpoint(client: TestClient) -> None:
    """POST /upload should successfully upload a video file via HTTP."""
    file_data = {"file": ("test.mp4", io.BytesIO(b"dummy mp4 data"), "video/mp4")}
    
    response = client.post("/upload", files=file_data)
    assert response.status_code == 200
    res_json = response.json()
    assert res_json["original_filename"] == "test.mp4"
    assert res_json["status"] == "uploaded"
    
    # Clean up created record and file via API
    video_id = res_json["id"]
    del_res = client.delete(f"/upload/videos/{video_id}")
    assert del_res.status_code == 200
