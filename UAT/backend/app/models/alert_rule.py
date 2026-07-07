"""Alert rule ORM model — defines notification trigger conditions for routes."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Index

from ..database import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, nullable=False)
    route_id = Column(String(200), nullable=False)
    route_name = Column(String(200), nullable=True)
    condition_type = Column(String(30), nullable=False)  # JWT_FAILURE, UPSTREAM_ERROR, HIGH_ERROR_RATE, HEALTH_CHECK_FAILURE
    threshold = Column(Integer, nullable=False)
    recipients = Column(Text, nullable=False)  # JSON array of email strings
    cooldown_seconds = Column(Integer, nullable=False, default=300)
    enabled = Column(Boolean, default=True, nullable=False)
    health_check_url = Column(String(500), nullable=True)  # For HEALTH_CHECK_FAILURE type
    health_check_interval = Column(Integer, nullable=True, default=60)
    health_check_failures_threshold = Column(Integer, nullable=True, default=3)
    notify_controlm = Column(Boolean, default=False, nullable=False)
    critical = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_alert_rules_name", "name"),
        Index("ix_alert_rules_route_id", "route_id"),
        Index("ix_alert_rules_condition_type", "condition_type"),
    )
