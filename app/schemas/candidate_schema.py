"""Pydantic schemas for candidate clips."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CandidateDetail(BaseModel):
    """Candidate clip detail."""

    id: int
    video_id: int
    job_id: int
    start_time: float
    end_time: float
    final_score: float
    score_breakdown: dict[str, Any] = {}
    hook_text: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateList(BaseModel):
    """List of candidate clips."""

    items: list[CandidateDetail]
    total: int


class CandidateAction(BaseModel):
    """Action on a candidate (select/reject)."""

    action: str
