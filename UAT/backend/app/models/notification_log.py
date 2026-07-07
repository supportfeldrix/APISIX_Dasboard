"""Notification log ORM model — records all sent/failed email notifications."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index

from ..database import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    alert_rule_id = Column(
        Integer,
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    route_id = Column(String(200), nullable=False)
    route_name = Column(String(200), nullable=True)
    condition_type = Column(String(30), nullable=False)  # JWT_FAILURE, UPSTREAM_ERROR, HIGH_ERROR_RATE, HEALTH_CHECK_FAILURE
    recipients = Column(Text, nullable=False)  # JSON array of email strings
    subject = Column(String(500), nullable=False)
    delivery_status = Column(String(20), nullable=False)  # SENT, FAILED, RETRYING
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_notification_logs_timestamp", "timestamp"),
        Index("ix_notification_logs_route_id", "route_id"),
        Index("ix_notification_logs_condition_type", "condition_type"),
        Index("ix_notification_logs_delivery_status", "delivery_status"),
    )
