"""Pydantic schemas for jobs and job steps."""

from datetime import datetime

from pydantic import BaseModel


class JobCreate(BaseModel):
    """Request to create a new pipeline job."""

    video_id: int
    pipeline_name: str = "auto_clipper_v1"
    language: str | None = None
    category_id: int | None = None
    clip_objective: str | None = None
    min_clip_duration: int = 30
    max_clip_duration: int = 60
    num_clips: int = 5
    keyword_boost: list[str] = []
    skip_keywords: list[str] = []
    analyze_start_time: float | None = None
    analyze_end_time: float | None = None
    subtitle_enabled: bool = False
    subtitle_style: str = "minimal"
    auto_reframe: bool = False
    face_tracking: bool = False
    voice_emotion: bool = True
    face_emotion: bool = False
    min_clip_duration: int = 30
    max_clip_duration: int = 60
    num_clips: int = 5
    keyword_boost: list[str] = []
    skip_keywords: list[str] = []
    analyze_start_time: float | None = None
    analyze_end_time: float | None = None
    subtitle_enabled: bool = False
    subtitle_style: str = "minimal"
    auto_reframe: bool = False
    face_tracking: bool = False
    voice_emotion: bool = True
    face_emotion: bool = False


class JobStepDetail(BaseModel):
    """Detail of a single pipeline step."""

    id: int
    step_name: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class JobDetail(BaseModel):
    """Full job detail response."""

    id: int
    video_id: int
    pipeline_name: str
    status: str
    current_step: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    steps: list[JobStepDetail] = []

    model_config = {"from_attributes": True}
