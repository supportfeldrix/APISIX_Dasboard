"""Metrics router — exposes APISIX Prometheus metrics as structured JSON."""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.metrics_service import fetch_metrics, parse_prometheus, parse_apisix_metrics

logger = logging.getLogger(__name__)
router = APIRouter()


class MetricsResponse(BaseModel):
    timestamp: datetime
    pods: List[dict]
    apisix: Dict[str, Any] = {}


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(current_user: User = Depends(get_current_user)):
    """Fetch and return structured metrics from the APISIX Prometheus endpoint."""
    raw = fetch_metrics()
    pod_metrics = parse_prometheus(raw)
    apisix_metrics = parse_apisix_metrics(raw)

    return MetricsResponse(
        timestamp=datetime.now(timezone.utc),
        pods=[
            {
                "pod": pm.pod,
                "cpu_usage": pm.cpu_usage,
                "memory_bytes": pm.memory_bytes,
            }
            for pm in pod_metrics
        ],
        apisix=apisix_metrics,
    )


@router.get("/metrics/routes")
def get_route_metrics(current_user: User = Depends(get_current_user)):
    """Get per-route request counts and status code breakdown.

    Returns a list of routes with their total hit count and per-status-code breakdown.
    """
    raw = fetch_metrics()
    apisix_metrics = parse_apisix_metrics(raw)
    route_requests = apisix_metrics.get("route_requests", {})

    # Enrich with route names from APISIX Admin API
    route_names = _get_route_names()

    routes = []
    for route_id, data in route_requests.items():
        routes.append({
            "route_id": route_id,
            "route_name": route_names.get(route_id, route_id),
            "total_requests": int(data["total"]),
            "by_status": {k: int(v) for k, v in data.get("by_status", {}).items()},
            "success_count": int(sum(v for k, v in data.get("by_status", {}).items() if k.startswith("2"))),
            "error_count": int(sum(v for k, v in data.get("by_status", {}).items() if k.startswith(("4", "5")))),
        })

    # Sort by total requests descending
    routes.sort(key=lambda r: r["total_requests"], reverse=True)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "routes": routes,
        "total_routes": len(routes),
    }


@router.get("/metrics/routes/csv")
def export_route_metrics_csv(current_user: User = Depends(get_current_user)):
    """Export per-route request metrics as a CSV file for audit/business reporting.

    Columns: Route ID, Route Name, Total Requests, 2xx, 3xx, 4xx, 5xx, Success Rate (%)
    """
    raw = fetch_metrics()
    apisix_metrics = parse_apisix_metrics(raw)
    route_requests = apisix_metrics.get("route_requests", {})
    route_names = _get_route_names()

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Route ID",
        "Route Name",
        "Total Requests",
        "2xx (Success)",
        "3xx (Redirect)",
        "4xx (Client Error)",
        "5xx (Server Error)",
        "Success Rate (%)",
        "Timestamp",
    ])

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Sort by total requests descending
    sorted_routes = sorted(route_requests.items(), key=lambda x: x[1]["total"], reverse=True)

    for route_id, data in sorted_routes:
        by_status = data.get("by_status", {})
        total = int(data["total"])
        count_2xx = int(sum(v for k, v in by_status.items() if k.startswith("2")))
        count_3xx = int(sum(v for k, v in by_status.items() if k.startswith("3")))
        count_4xx = int(sum(v for k, v in by_status.items() if k.startswith("4")))
        count_5xx = int(sum(v for k, v in by_status.items() if k.startswith("5")))
        success_rate = round((count_2xx / total) * 100, 2) if total > 0 else 0.0

        writer.writerow([
            route_id,
            route_names.get(route_id, route_id),
            total,
            count_2xx,
            count_3xx,
            count_4xx,
            count_5xx,
            success_rate,
            timestamp,
        ])

    output.seek(0)
    filename = f"route_metrics_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _get_route_names() -> Dict[str, str]:
    """Fetch route names from APISIX Admin API for enrichment."""
    import httpx
    from app.config import settings

    try:
        base_url = settings.APISIX_ADMIN_BASE_URL.rstrip("/")
        url = f"{base_url}/apisix/admin/routes"

        with httpx.Client(
            verify=settings.APISIX_ADMIN_VERIFY_SSL,
            timeout=httpx.Timeout(settings.APISIX_ADMIN_TIMEOUT),
        ) as client:
            response = client.get(url, headers={"X-API-KEY": settings.APISIX_ADMIN_KEY})

        if response.status_code != 200:
            return {}

        data = response.json()
        # APISIX v3 format: {"list": [{"value": {"id": "...", "name": "..."}}]}
        routes_list = data.get("list") or data.get("node", {}).get("nodes", [])
        names = {}
        for entry in routes_list:
            value = entry.get("value") or entry
            route_id = str(value.get("id", ""))
            route_name = value.get("name") or value.get("uri") or route_id
            if route_id:
                names[route_id] = route_name
        return names

    except Exception as exc:
        logger.warning("Failed to fetch route names: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Traffic Report endpoints (per-minute breakdown from APISIX access logs)
# ---------------------------------------------------------------------------


@router.get("/metrics/traffic-report")
def get_traffic_report_endpoint(
    route_id: str = Query(..., description="Route ID to filter"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    time_from: Optional[str] = Query("00:00", description="Start time HH:MM"),
    time_to: Optional[str] = Query("23:59", description="End time HH:MM"),
    current_user: User = Depends(get_current_user),
):
    """Get per-minute traffic breakdown for a route on a given date.

    Reads APISIX access logs from both pods and groups requests per minute.
    Returns per-minute counts, average latency, and status code breakdown.
    """
    from app.services.traffic_report_service import get_traffic_report

    result = get_traffic_report(route_id, date, time_from, time_to)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/metrics/traffic-report/csv")
def export_traffic_report_csv(
    route_id: str = Query(..., description="Route ID to filter"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    time_from: Optional[str] = Query("00:00", description="Start time HH:MM"),
    time_to: Optional[str] = Query("23:59", description="End time HH:MM"),
    current_user: User = Depends(get_current_user),
):
    """Export per-minute traffic report as CSV for audit/business reporting.

    Columns: Date, Time (HH:MM), Route, Request Count, Avg Latency (ms), 2xx, 4xx, 5xx
    """
    from app.services.traffic_report_service import get_traffic_report, ROUTE_NAMES

    result = get_traffic_report(route_id, date, time_from, time_to)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=result["error"])

    # Resolve friendly route name for CSV output
    route_display_name = ROUTE_NAMES.get(route_id, route_id)

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Time (HH:MM)", "Route", "Request Count",
        "Avg Latency (ms)", "2xx", "4xx", "5xx",
    ])

    for minute in result.get("minutes", []):
        statuses = minute.get("statuses", {})
        count_2xx = sum(v for k, v in statuses.items() if k.startswith("2"))
        count_4xx = sum(v for k, v in statuses.items() if k.startswith("4"))
        count_5xx = sum(v for k, v in statuses.items() if k.startswith("5"))

        writer.writerow([
            date,
            minute["time"],
            route_display_name,
            minute["count"],
            minute["avg_latency_ms"],
            count_2xx,
            count_4xx,
            count_5xx,
        ])

    # Summary row
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow(["Total Requests", result.get("total_requests", 0)])
    writer.writerow(["Avg Latency (ms)", result.get("avg_latency_ms", 0)])
    writer.writerow(["Peak Per Minute", result.get("peak_per_minute", 0)])
    writer.writerow(["Pods Queried", ", ".join(result.get("pods_queried", []))])

    output.seek(0)
    filename = f"traffic_report_{route_display_name}_{date}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/metrics/traffic-report/routes")
def get_available_report_routes(
    current_user: User = Depends(get_current_user),
):
    """Get the list of routes available for traffic reporting."""
    from app.services.traffic_report_service import get_available_routes
    return {"routes": get_available_routes()}
