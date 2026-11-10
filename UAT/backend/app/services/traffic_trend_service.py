"""Traffic trend service — snapshots per-route counters and reads them as trends.

APISIX exposes cumulative counters only, with no history. This service captures
periodic snapshots (driven by the background scheduler) into the
`route_traffic_snapshots` table, then computes per-interval deltas on read so the
frontend can chart requests/min and error-rate over time.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import delete

from app.models.route_traffic_snapshot import RouteTrafficSnapshot
from app.services.metrics_service import (
    fetch_metrics,
    parse_apisix_metrics,
    parse_route_latency,
)

logger = logging.getLogger(__name__)

# How long to keep snapshots. Keeps the table bounded; trend view covers recent history.
SNAPSHOT_RETENTION_DAYS = 7


def capture_snapshot(db) -> int:
    """Capture one snapshot row per route from the current metrics.

    Returns the number of route rows written. Best-effort: logs and returns 0 on
    failure so it never breaks the scheduler cycle.
    """
    try:
        raw = fetch_metrics()
    except Exception as exc:  # noqa: BLE001 - never break the scheduler
        logger.warning("Traffic snapshot skipped — metrics unavailable: %s", exc)
        return 0

    try:
        apisix = parse_apisix_metrics(raw)
        route_requests = apisix.get("route_requests", {})
        latency = parse_route_latency(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Traffic snapshot skipped — parse error: %s", exc)
        return 0

    now = datetime.now(timezone.utc)
    written = 0

    for route_id, data in route_requests.items():
        by_status = data.get("by_status", {})
        c2 = int(sum(v for k, v in by_status.items() if k.startswith("2")))
        c4 = int(sum(v for k, v in by_status.items() if k.startswith("4")))
        c5 = int(sum(v for k, v in by_status.items() if k.startswith("5")))

        req_latency = latency.get(route_id, {}).get("request", {})

        db.add(RouteTrafficSnapshot(
            timestamp=now,
            route_id=route_id,
            route_name=route_id,  # UAT/PROD metrics key by friendly route name
            total_requests=int(data.get("total", 0)),
            count_2xx=c2,
            count_4xx=c4,
            count_5xx=c5,
            p50_ms=req_latency.get("p50"),
            p95_ms=req_latency.get("p95"),
            p99_ms=req_latency.get("p99"),
        ))
        written += 1

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Traffic snapshot commit failed: %s", exc)
        db.rollback()
        return 0

    return written


def purge_old_snapshots(db) -> int:
    """Delete snapshots older than the retention window. Returns rows deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    try:
        result = db.execute(
            delete(RouteTrafficSnapshot).where(RouteTrafficSnapshot.timestamp < cutoff)
        )
        db.commit()
        return result.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        logger.error("Purge of old traffic snapshots failed: %s", exc)
        db.rollback()
        return 0


def get_trend(db, route_id: str, hours: int = 1) -> Dict[str, Any]:
    """Return a per-interval trend for one route over the last `hours` hours.

    Computes deltas between consecutive snapshots. A counter reset (current < prev,
    e.g. after an APISIX pod restart) is treated as a zero delta for that interval
    so the chart does not show a large negative spike.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows: List[RouteTrafficSnapshot] = (
        db.query(RouteTrafficSnapshot)
        .filter(
            RouteTrafficSnapshot.route_id == route_id,
            RouteTrafficSnapshot.timestamp >= since,
        )
        .order_by(RouteTrafficSnapshot.timestamp.asc())
        .all()
    )

    points: List[Dict[str, Any]] = []
    prev = None
    for row in rows:
        if prev is not None:
            def _delta(curr_v, prev_v):
                d = (curr_v or 0) - (prev_v or 0)
                return d if d >= 0 else 0

            d_total = _delta(row.total_requests, prev.total_requests)
            d_2xx = _delta(row.count_2xx, prev.count_2xx)
            d_4xx = _delta(row.count_4xx, prev.count_4xx)
            d_5xx = _delta(row.count_5xx, prev.count_5xx)
            errors = d_4xx + d_5xx
            error_rate = round((errors / d_total) * 100, 2) if d_total > 0 else 0.0

            points.append({
                "time": row.timestamp.replace(tzinfo=timezone.utc).isoformat(),
                "requests": d_total,
                "count_2xx": d_2xx,
                "count_4xx": d_4xx,
                "count_5xx": d_5xx,
                "error_rate": error_rate,
                "p95_ms": row.p95_ms,
                "p99_ms": row.p99_ms,
            })
        prev = row

    return {
        "route_id": route_id,
        "hours": hours,
        "points": points,
        "sample_count": len(points),
    }
