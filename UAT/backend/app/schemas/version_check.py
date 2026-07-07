"""Pydantic schemas for version check endpoints."""
from pydantic import BaseModel


class VersionCheckResponse(BaseModel):
    running_version: str | None
    latest_version: str | None
    update_available: bool
    last_checked: str  # ISO 8601 timestamp
    check_successful: bool
    error_message: str | None = None
