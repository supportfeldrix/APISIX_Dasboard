"""Escalation router — manage ControlM escalation settings, status, acknowledgment, and history.

Includes pull-based trigger file delivery endpoints for the Linux server pull script.
"""
import glob
import logging
import os
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings as app_settings
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


# ===========================================================================
# Pull-based trigger file delivery — used by the Linux server cron script
# ===========================================================================

# These endpoints authenticate via an API key header (X-ControlM-Key) rather
# than JWT, so the Linux pull script doesn't need user credentials.

_SAFE_FILENAME_RE = re.compile(r"^CROIT_(ALERT|RECOVERY)_[a-zA-Z0-9_]+_\d{8}_\d{6}\.trigger$")


def _verify_pull_api_key(x_controlm_key: str = Header(...)) -> None:
    """Verify the shared API key from the pull script.

    Raises 401 if the key is missing or doesn't match the configured value.
    Raises 503 if no API key is configured on the server (feature not enabled).
    """
    configured_key = app_settings.CONTROLM_PULL_API_KEY
    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="ControlM pull API key not configured on the server.",
        )
    if x_controlm_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")


def _get_landing_zone_path() -> str:
    """Read landing zone path from the database (singleton settings row)."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(ControlMSettings).filter(ControlMSettings.id == 1).first()
        if row and row.landing_zone:
            return row.landing_zone
        return "/app/data/controlm_alerts/"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /escalation/pending-triggers — list trigger files ready for pickup
# ---------------------------------------------------------------------------


@router.get("/escalation/pending-triggers")
def list_pending_triggers(
    _: None = Depends(_verify_pull_api_key),
):
    """List all .trigger files currently in the landing zone.

    Returns filenames and metadata so the pull script knows what to download.
    Authenticated via X-ControlM-Key header.
    """
    landing_zone = _get_landing_zone_path()

    if not os.path.isdir(landing_zone):
        return {"files": [], "landing_zone": landing_zone}

    # List only .trigger files (not temp files)
    pattern = os.path.join(landing_zone, "CROIT_*.trigger")
    file_paths = glob.glob(pattern)

    files = []
    for fp in sorted(file_paths):
        filename = os.path.basename(fp)
        # Skip temp files
        if filename.startswith(".tmp_"):
            continue
        try:
            stat = os.stat(fp)
            files.append(
                {
                    "filename": filename,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                }
            )
        except OSError:
            # File may have been deleted between listing and stat
            continue

    return {"files": files, "landing_zone": landing_zone}


# ---------------------------------------------------------------------------
# GET /escalation/download-trigger/{filename} — download a specific trigger file
# ---------------------------------------------------------------------------


@router.get("/escalation/download-trigger/{filename}")
def download_trigger_file(
    filename: str,
    _: None = Depends(_verify_pull_api_key),
):
    """Download the content of a specific trigger file.

    Returns the file content as plain text. The pull script writes this
    to the local landing zone on the Linux server.
    Authenticated via X-ControlM-Key header.
    """
    # Validate filename format to prevent path traversal
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename format. Expected CROIT_ALERT_*_YYYYMMDD_HHMMSS.trigger",
        )

    landing_zone = _get_landing_zone_path()
    file_path = os.path.join(landing_zone, filename)

    # Ensure the resolved path is still inside the landing zone (double check)
    real_landing = os.path.realpath(landing_zone)
    real_file = os.path.realpath(file_path)
    if not real_file.startswith(real_landing):
        raise HTTPException(status_code=400, detail="Invalid file path.")

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {e}")

    return PlainTextResponse(content=content, media_type="text/plain")


# ---------------------------------------------------------------------------
# POST /escalation/acknowledge-pickup/{filename} — confirm file was received
# ---------------------------------------------------------------------------


@router.post("/escalation/acknowledge-pickup/{filename}")
def acknowledge_trigger_pickup(
    filename: str,
    _: None = Depends(_verify_pull_api_key),
):
    """Confirm a trigger file was successfully received by the pull script.

    Moves the file to a .picked_up subdirectory (for audit) rather than deleting.
    Authenticated via X-ControlM-Key header.
    """
    # Validate filename format to prevent path traversal
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename format.",
        )

    landing_zone = _get_landing_zone_path()
    file_path = os.path.join(landing_zone, filename)

    # Path traversal guard
    real_landing = os.path.realpath(landing_zone)
    real_file = os.path.realpath(file_path)
    if not real_file.startswith(real_landing):
        raise HTTPException(status_code=400, detail="Invalid file path.")

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # Move to .picked_up subdirectory for audit trail
    picked_up_dir = os.path.join(landing_zone, ".picked_up")
    os.makedirs(picked_up_dir, exist_ok=True)
    dest_path = os.path.join(picked_up_dir, filename)

    try:
        os.rename(file_path, dest_path)
    except OSError as e:
        raise HTTPException(
            status_code=500, detail=f"Error archiving file: {e}"
        )

    logger.info(
        "Trigger file picked up by pull script: %s → %s", file_path, dest_path
    )

    return {"success": True, "message": f"File '{filename}' acknowledged and archived."}
