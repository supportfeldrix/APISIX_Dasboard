"""APISIX Admin API proxy service."""
import logging
import time
from typing import Optional

import httpx
from fastapi import HTTPException

from app.config import settings
from app.utils.yaml_converter import yaml_to_json

logger = logging.getLogger(__name__)

ALLOWED_RESOURCES: frozenset = frozenset({
    "routes",
    "services",
    "upstreams",
    "consumers",
    "plugins",
    "ssl",
    "global_rules",
    "plugin_metadata",
})


def get_http_client() -> httpx.Client:
    """Create a synchronous httpx client with configured timeout and SSL settings."""
    return httpx.Client(
        verify=settings.APISIX_ADMIN_VERIFY_SSL,
        timeout=httpx.Timeout(
            connect=settings.APISIX_ADMIN_TIMEOUT,
            read=settings.APISIX_ADMIN_TIMEOUT,
            write=settings.APISIX_ADMIN_TIMEOUT,
            pool=settings.APISIX_ADMIN_TIMEOUT,
        ),
    )


def convert_body_if_yaml(body: bytes, content_type: str) -> tuple[bytes, str]:
    """If the content type indicates YAML, convert body to JSON."""
    if content_type and ("yaml" in content_type.lower()):
        try:
            json_str = yaml_to_json(body.decode("utf-8"))
            return json_str.encode("utf-8"), "application/json"
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return body, content_type


def forward_request(
    method: str,
    resource_type: str,
    sub_path: str,
    body: Optional[bytes],
    query_params: dict,
    content_type: str,
    username: str,
) -> httpx.Response:
    """Validate, proxy, and log a request to the APISIX Admin API."""
    # Validate resource type against allowlist
    if resource_type not in ALLOWED_RESOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Resource type not permitted: {resource_type}",
        )

    # Convert YAML body to JSON if needed
    if body:
        body, content_type = convert_body_if_yaml(body, content_type)

    # Build target URL
    base = settings.APISIX_ADMIN_BASE_URL.rstrip("/")
    path = f"/apisix/admin/{resource_type}"
    if sub_path:
        path = f"{path}/{sub_path.lstrip('/')}"
    url = f"{base}{path}"

    headers = {
        "X-API-KEY": settings.APISIX_ADMIN_KEY,
        "Content-Type": content_type or "application/json",
    }

    start = time.monotonic()
    try:
        with get_http_client() as client:
            response = client.request(
                method=method.upper(),
                url=url,
                content=body,
                params=query_params,
                headers=headers,
            )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("APISIX Admin API unreachable: %s", e)
        raise HTTPException(status_code=503, detail="APISIX Admin API unreachable")

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "PROXY | %s | %s | %s/%s | %s | %dms",
        username,
        method.upper(),
        resource_type,
        sub_path or "",
        response.status_code,
        duration_ms,
    )

    return response
