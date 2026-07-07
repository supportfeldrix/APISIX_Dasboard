"""Pydantic schemas for SSL upload endpoints."""
from pydantic import BaseModel


class SSLUploadResponse(BaseModel):
    status: str  # "success" or "error"
    apisix_response: dict | None = None
    detail: str | None = None
