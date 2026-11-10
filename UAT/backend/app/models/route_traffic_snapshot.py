"""Route traffic snapshot ORM model — periodic point-in-time per-route counters.

The APISIX Prometheus metrics are cumulative counters with no history. To draw
traffic trend charts we snapshot the current per-route totals on each scheduler
cycle. Trend deltas (requests/errors per interval) are computed at read time by
diffing consecutive snapshots.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Float, Index

from ..database import Base


class RouteTrafficSnapshot(Base):
    __tablename__ = "route_traffic_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    route_id = Column(String(200), nullable=False)
    route_name = Column(String(200), nullable=True)

    # Cumulative counters captured at this instant.
    total_requests = Column(Integer, nullable=False, default=0)
    count_2xx = Column(Integer, nullable=False, default=0)
    count_4xx = Column(Integer, nullable=False, default=0)
    count_5xx = Column(Integer, nullable=False, default=0)

    # Latency percentile estimates (ms) for total request time at capture instant.
    p50_ms = Column(Float, nullable=True)
    p95_ms = Column(Float, nullable=True)
    p99_ms = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_route_traffic_snapshots_timestamp", "timestamp"),
        Index("ix_route_traffic_snapshots_route_id", "route_id"),
        Index("ix_rts_route_ts", "route_id", "timestamp"),
    )
