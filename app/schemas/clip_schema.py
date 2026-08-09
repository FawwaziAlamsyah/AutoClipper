"""Pydantic schemas for clips."""

from datetime import datetime

from pydantic import BaseModel


class ClipDetail(BaseModel):
    """Final clip detail."""

    id: int
    candidate_id: int | None = None
    video_id: int
    file_path: str
    start_time: float
    end_time: float
    aspect_ratio: str
    has_subtitle: bool
    status: str
    exported_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClipGenerateRequest(BaseModel):
    """Request to generate a clip from a candidate."""

    candidate_id: int
    aspect_ratio: str = "9:16"
    subtitle_enabled: bool = False
    subtitle_style: str = "minimal"
