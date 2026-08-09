"""Pydantic schemas for history."""

from datetime import datetime

from pydantic import BaseModel


class HistoryDetail(BaseModel):
    """Single history entry."""

    id: int
    video_id: int | None = None
    job_id: int | None = None
    action: str
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class HistoryList(BaseModel):
    """Paginated history list."""

    items: list[HistoryDetail]
    total: int
