"""Version check result model — stores the latest APISIX version comparison outcome."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text

from app.database import Base


class VersionCheckResult(Base):
    __tablename__ = "version_check_results"

    id = Column(Integer, primary_key=True, index=True)
    running_version = Column(String(50), nullable=True)       # e.g., "3.8.0" or None
    latest_version = Column(String(50), nullable=True)        # e.g., "3.9.1" or None
    update_available = Column(Boolean, nullable=False, default=False)
    check_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    check_successful = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)               # Populated on failure
