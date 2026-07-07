"""Escalation log ORM model — audit trail for all ControlM escalation events."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index

from ..database import Base


class EscalationLog(Base):
    __tablename__ = "escalation_logs"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(
        Integer,
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    rule_name = Column(String(200), nullable=False)
    event_type = Column(String(30), nullable=False)
    # event_types: trigger_file_written, trigger_file_failed,
    #              acknowledged, grace_period_expired,
    #              recovery_file_written, recovery_cancelled_pending
    file_path = Column(String(500), nullable=True)
    username = Column(String(128), nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_escalation_logs_rule_time", "rule_id", "created_at"),
        Index("ix_escalation_logs_time", "created_at"),
    )
