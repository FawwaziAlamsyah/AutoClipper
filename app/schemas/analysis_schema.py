"""Pydantic schemas for analysis results."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AnalysisResultDetail(BaseModel):
    """Single analysis result."""

    id: int
    video_id: int
    job_id: int
    analyzer_type: str
    start_time: float | None = None
    end_time: float | None = None
    score: float | None = None
    result_data: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisResultList(BaseModel):
    """List of analysis results grouped by analyzer type."""

    items: list[AnalysisResultDetail]
    total: int
