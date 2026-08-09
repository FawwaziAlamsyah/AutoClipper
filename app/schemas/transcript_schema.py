"""Pydantic schemas for transcript and segments."""

from datetime import datetime

from pydantic import BaseModel


class TranscriptSegmentDetail(BaseModel):
    """Single transcript segment."""

    id: int
    start_time: float
    end_time: float
    text: str
    confidence: float | None = None
    speaker_label: str | None = None

    model_config = {"from_attributes": True}


class TranscriptDetail(BaseModel):
    """Full transcript response."""

    id: int
    video_id: int
    job_id: int
    engine: str
    language: str | None = None
    full_text: str
    segments: list[TranscriptSegmentDetail] = []
    created_at: datetime

    model_config = {"from_attributes": True}
