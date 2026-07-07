"""Escalation state ORM model — tracks per-rule escalation lifecycle."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey

from ..database import Base


class EscalationState(Base):
    __tablename__ = "escalation_state"

    rule_id = Column(
        Integer,
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    state = Column(String(20), nullable=False, default="idle")  # idle, pending, escalated
    grace_started_at = Column(DateTime, nullable=True)
    grace_expires_at = Column(DateTime, nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    trigger_file = Column(String(500), nullable=True)
    failure_message = Column(Text, nullable=True)
