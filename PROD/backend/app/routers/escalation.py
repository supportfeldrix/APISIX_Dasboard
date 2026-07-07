"""Escalation router — manage ControlM escalation settings, status, acknowledgment, and history."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.controlm_settings import ControlMSettings
from app.models.escalation_log import EscalationLog
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.controlm_escalation_service import escalation_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["escalation"])


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------


class EscalationSettingsPayload(BaseModel):
    controlm_enabled: bool
    landing_zone: str
    grace_period: int


# ---------------------------------------------------------------------------
# GET /escalation/settings — admin only
# ---------------------------------------------------------------------------


@router.get("/escalation/settings")
def get_escalation_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current ControlM escalation settings."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    row = db.query(ControlMSettings).filter(ControlMSettings.id == 1).first()

    if row is None:
        return {
            "controlm_enabled": False,
            "landing_zone": "/app/data/controlm_alerts/",
            "grace_period": 0,
        }

    return {
        "controlm_enabled": row.controlm_enabled,
        "landing_zone": row.landing_zone,
        "grace_period": row.grace_period,
    }


# ---------------------------------------------------------------------------
# PUT /escalation/settings — admin only
# ---------------------------------------------------------------------------


@router.put("/escalation/settings")
def update_escalation_settings(
    body: EscalationSettingsPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update ControlM escalation settings (landing zone, grace period, global toggle)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Validate landing_zone: 1-500 chars
    if not body.landing_zone or len(body.landing_zone) < 1:
        raise HTTPException(
            status_code=400,
            detail="landing_zone must be at least 1 character.",
        )
    if len(body.landing_zone) > 500:
        raise HTTPException(
            status_code=400,
            detail="landing_zone must not exceed 500 characters.",
        )

    # Validate grace_period: int 0-86400
    if not isinstance(body.grace_period, int):
        raise HTTPException(
            status_code=400,
            detail="grace_period must be an integer.",
        )
    if body.grace_period < 0 or body.grace_period > 86400:
        raise HTTPException(
            status_code=400,
            detail="grace_period must be between 0 and 86400 seconds.",
        )

    # Upsert ControlMSettings row (singleton id=1)
    from datetime import timezone

    settings_row = ControlMSettings(
        id=1,
        controlm_enabled=body.controlm_enabled,
        landing_zone=body.landing_zone,
        grace_period=body.grace_period,
        updated_at=datetime.now(timezone.utc),
    )
    db.merge(settings_row)
    db.commit()

    logger.info(
        "ControlM escalation settings updated by user '%s': enabled=%s, landing_zone='%s', grace_period=%d",
        current_user.username,
        body.controlm_enabled,
        body.landing_zone,
        body.grace_period,
    )

    return {"ok": True, "message": "ControlM escalation settings updated."}


# ---------------------------------------------------------------------------
# POST /escalation/acknowledge/{rule_id} — admin or viewer
# ---------------------------------------------------------------------------


@router.post("/escalation/acknowledge/{rule_id}")
async def acknowledge_escalation(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Acknowledge a pending escalation for a rule."""
    if current_user.role not in ("admin", "viewer"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    success, message = await escalation_service.acknowledge(
        rule_id, current_user.username, db
    )

    if not success:
        if "No pending escalation" in message:
            raise HTTPException(status_code=409, detail=message)
        elif "already occurred" in message:
            raise HTTPException(status_code=409, detail=message)
        else:
            raise HTTPException(status_code=404, detail=message)

    return {"success": True, "message": message}


# ---------------------------------------------------------------------------
# GET /escalation/status — admin or viewer
# ---------------------------------------------------------------------------


@router.get("/escalation/status")
def get_all_escalation_statuses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get escalation statuses for all rules."""
    if current_user.role not in ("admin", "viewer"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    statuses = escalation_service.get_all_statuses(db)

    # Convert integer keys to strings for JSON serialization
    return {"statuses": {str(k): v for k, v in statuses.items()}}


# ---------------------------------------------------------------------------
# GET /escalation/status/{rule_id} — admin or viewer
# ---------------------------------------------------------------------------


@router.get("/escalation/status/{rule_id}")
def get_single_escalation_status(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get escalation status for a single rule."""
    if current_user.role not in ("admin", "viewer"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return escalation_service.get_escalation_status(rule_id, db)


# ---------------------------------------------------------------------------
# GET /escalation/history — admin or viewer
# ---------------------------------------------------------------------------


@router.get("/escalation/history")
def get_escalation_history(
    rule_name: Optional[str] = Query(None, description="Filter by rule name (partial match)"),
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    limit: Optional[int] = Query(100, ge=1, le=1000, description="Max results (1-1000)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Query escalation audit log with optional filters."""
    if current_user.role not in ("admin", "viewer"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    query = db.query(EscalationLog)

    # Filter by rule_name (partial match, case-insensitive)
    if rule_name:
        query = query.filter(EscalationLog.rule_name.ilike(f"%{rule_name}%"))

    # Filter by start_date
    if start_date:
        try:
            parsed_start = datetime.fromisoformat(start_date)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400, detail="Invalid start_date format. Use ISO 8601."
            )
        query = query.filter(EscalationLog.created_at >= parsed_start)

    # Filter by end_date
    if end_date:
        try:
            parsed_end = datetime.fromisoformat(end_date)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400, detail="Invalid end_date format. Use ISO 8601."
            )
        query = query.filter(EscalationLog.created_at <= parsed_end)

    # Get total count before applying limit
    total = query.count()

    # Cap limit at 1000
    effective_limit = min(limit or 100, 1000)

    # Sort by created_at descending, apply limit
    rows = (
        query.order_by(EscalationLog.created_at.desc())
        .limit(effective_limit)
        .all()
    )

    items = [
        {
            "id": row.id,
            "rule_id": row.rule_id,
            "rule_name": row.rule_name,
            "event_type": row.event_type,
            "file_path": row.file_path,
            "username": row.username,
            "error_msg": row.error_msg,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

    return {"items": items, "total": total}
