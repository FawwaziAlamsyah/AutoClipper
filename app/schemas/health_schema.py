"""Pydantic schemas for the health endpoint."""

from datetime import datetime

from pydantic import BaseModel


class HealthStatus(BaseModel):
    """Response schema describing application health."""

    status: str
    app_name: str
    environment: str
    checked_at: datetime
