"""ControlM settings ORM model — singleton row for global escalation configuration."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, DateTime

from ..database import Base


class ControlMSettings(Base):
    __tablename__ = "controlm_settings"

    id = Column(Integer, primary_key=True, default=1)  # singleton row
    controlm_enabled = Column(Boolean, default=False, nullable=False)
    landing_zone = Column(String(500), default="/app/data/controlm_alerts/", nullable=False)
    grace_period = Column(Integer, default=0, nullable=False)  # seconds
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
