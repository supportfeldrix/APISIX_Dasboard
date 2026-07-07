"""Pydantic schemas for APISIX resource payloads and proxy errors."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class RoutePayload(BaseModel):
    uri: str
    name: Optional[str] = None
    methods: Optional[List[str]] = None
    upstream_id: Optional[str] = None
    plugins: Optional[Dict[str, Any]] = None
    status: Optional[int] = None


class ServicePayload(BaseModel):
    name: Optional[str] = None
    upstream_id: Optional[str] = None
    plugins: Optional[Dict[str, Any]] = None


class UpstreamPayload(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    nodes: Optional[Dict[str, Any]] = None


class ConsumerPayload(BaseModel):
    username: str
    plugins: Optional[Dict[str, Any]] = None


class SSLPayload(BaseModel):
    cert: str
    key: str
    snis: Optional[List[str]] = None


class ProxyError(BaseModel):
    detail: str
    status_code: int
