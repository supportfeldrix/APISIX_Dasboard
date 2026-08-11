"""Logs router — view APISIX route logs from the dashboard."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.traffic_report_service import (
    _exec_in_pod,
    APISIX_PODS,
    LOG_FILES,
    ROUTE_NAMES,
    LOG_BASE_PATH,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["logs"])


@router.get("/logs/files")
def get_log_files(current_user: User = Depends(get_current_user)):
    """Get available log files and pods for the log viewer."""
    files = []
    for route_id, log_file in LOG_FILES.items():
        files.append({
            "file": log_file,
            "label": ROUTE_NAMES.get(route_id, route_id),
            "route_id": route_id,
        })

    return {
        "files": files,
        "pods": APISIX_PODS,
    }


@router.get("/logs/view")
def view_logs(
    file: str = Query(..., description="Log file name (e.g. rcm-route.log)"),
    pod: str = Query("apisix-0", description="Pod name"),
    lines: int = Query(100, ge=10, le=500, description="Number of lines to return"),
    search: Optional[str] = Query(None, description="Optional search/filter term"),
    current_user: User = Depends(get_current_user),
):
    """View the last N lines of a log file from an APISIX pod.

    Optionally filter lines by a search term (grep).
    """
    # Validate pod name
    if pod not in APISIX_PODS:
        raise HTTPException(status_code=400, detail=f"Invalid pod: {pod}. Must be one of {APISIX_PODS}")

    # Validate log file (prevent path traversal)
    allowed_files = set(LOG_FILES.values())
    allowed_files.add("access.log")
    allowed_files.add("error.log")
    if file not in allowed_files:
        raise HTTPException(status_code=400, detail=f"Invalid log file: {file}")

    log_path = f"{LOG_BASE_PATH}/{file}"

    # Build command
    if search and search.strip():
        # Sanitise search input — remove shell metacharacters
        safe_search = "".join(c for c in search.strip() if c.isalnum() or c in "._-/ @:=")
        # tail + grep for filtered view, cap tail depth at 5000
        tail_depth = min(lines * 5, 5000)
        cmd = ["sh", "-c", f"tail -{tail_depth} {log_path} | grep -a '{safe_search}' | tail -{lines}"]
    else:
        # Simple tail
        cmd = ["tail", f"-{lines}", log_path]

    try:
        output = _exec_in_pod(pod, cmd)
    except Exception as exc:
        logger.error("Failed to read logs from %s/%s: %s", pod, file, exc)
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {exc}")

    if not output:
        return {
            "pod": pod,
            "file": file,
            "lines": [],
            "total": 0,
        }

    log_lines = output.splitlines()

    return {
        "pod": pod,
        "file": file,
        "lines": log_lines,
        "total": len(log_lines),
        "search": search,
    }
