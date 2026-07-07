"""Audit logging service — records all user actions."""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    username: str,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
    status: str = "success",
) -> None:
    """Record an audit log entry."""
    entry = AuditLog(
        timestamp=datetime.now(timezone.utc),
        username=username,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        status=status,
    )
    db.add(entry)
    db.commit()
    logger.info(
        "AUDIT | %s | %s | %s/%s | %s | %s",
        username, action, resource_type or "-", resource_id or "-", status, details or ""
    )
