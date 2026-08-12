"""Pydantic schema for video processing request (pipeline parameters)."""

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    """User-configurable pipeline parameters."""

    language: str | None = Field(
        "id", description="id, en, atau kosong untuk auto-detect"
    )
    content_type: str = Field(
        "podcast",
        description="podcast | interview | gaming | education | streaming | news | motivation | custom",
    )
    clip_style: str = Field(
        "viral",
        description="viral | educational | funny | emotional | storytelling | controversial",
    )
    clip_objective: str | None = Field(None, description="Instruksi bebas, mis. cari bagian tentang investasi")
    min_clip_duration: int = Field(30, ge=5, le=600, description="Durasi minimum klip (detik)")
    max_clip_duration: int = Field(60, ge=10, le=900, description="Durasi maksimum klip (detik)")
    num_clips: int = Field(5, ge=1, le=20, description="Jumlah candidate clip yang dibuat")
    keyword_boost: list[str] = Field(default_factory=list, description="Keyword yang menaikkan score")
    skip_keywords: list[str] = Field(default_factory=list, description="Keyword yang memicu penalty (sponsor, subscribe, dll)")
    analyze_start_time: float | None = Field(None, description="Batasi analisis dari detik ini")
    analyze_end_time: float | None = Field(None, description="Batasi analisis sampai detik ini")
