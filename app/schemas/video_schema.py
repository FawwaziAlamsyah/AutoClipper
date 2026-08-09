"""Pydantic schemas for video upload and response."""

from datetime import datetime

from pydantic import BaseModel


class VideoUploadResponse(BaseModel):
    """Response after a video is uploaded."""

    id: int
    original_filename: str
    source_type: str
    file_path: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VideoDetail(BaseModel):
    """Full video detail response."""

    id: int
    original_filename: str
    source_type: str
    source_url: str | None = None
    file_path: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    file_size_bytes: int | None = None
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class VideoList(BaseModel):
    """Paginated video list."""

    items: list[VideoDetail]
    total: int


class VideoDownloadRequest(BaseModel):
    """Request to download a video from URL."""

    url: str
    filename: str | None = None
