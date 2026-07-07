"""Audit log router — view audit trail."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


class AuditLogEntry(BaseModel):
    id: int
    timestamp: datetime
    username: str
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    status: str

    class Config:
        from_attributes = True


@router.get("/audit", response_model=List[AuditLogEntry])
def get_audit_logs(
    limit: int = Query(100, le=500),
    action: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get audit log entries. Admin only."""
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin access required")

    query = db.query(AuditLog).order_by(AuditLog.timestamp.desc())

    if action:
        query = query.filter(AuditLog.action == action)
    if username:
        query = query.filter(AuditLog.username == username)

    return query.limit(limit).all()
