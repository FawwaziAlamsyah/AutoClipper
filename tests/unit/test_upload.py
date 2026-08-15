"""Tests for the video upload logic and endpoints."""

import io

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions.base import ValidationException
from app.models.job_model import JobModel
from app.models.video_model import VideoModel
from app.services.video_service import VideoService


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


def test_list_all_hides_training_only_videos(db_session: Session) -> None:
    """Upload list excludes training-only video but keeps unprocessed/discovery videos."""
    service = VideoService(db_session)
    unprocessed = VideoModel(
        original_filename="unprocessed.mp4",
        source_type="upload",
        file_path="unprocessed.mp4",
        status="uploaded",
    )
    training_only = VideoModel(
        original_filename="training.mp4",
        source_type="upload",
        file_path="training.mp4",
        status="ready",
    )
    discovery = VideoModel(
        original_filename="discovery.mp4",
        source_type="upload",
        file_path="discovery.mp4",
        status="ready",
    )
    mixed = VideoModel(
        original_filename="mixed.mp4",
        source_type="upload",
        file_path="mixed.mp4",
        status="ready",
    )
    db_session.add_all([unprocessed, training_only, discovery, mixed])
    db_session.flush()
    db_session.add_all([
        JobModel(video_id=training_only.id, pipeline_name="test", job_type="training_ingest", status="completed"),
        JobModel(video_id=discovery.id, pipeline_name="test", job_type="discovery", status="completed"),
        JobModel(video_id=mixed.id, pipeline_name="test", job_type="training_ingest", status="completed"),
        JobModel(video_id=mixed.id, pipeline_name="test", job_type="discovery", status="completed"),
    ])
    db_session.commit()

    videos = service.list_all()

    ids = {video.id for video in videos}
    assert unprocessed.id in ids
    assert discovery.id in ids
    assert mixed.id in ids
    assert training_only.id not in ids
    assert len([video for video in videos if video.id == mixed.id]) == 1


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
