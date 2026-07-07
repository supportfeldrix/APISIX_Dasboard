"""Notifications router — manage alert rules, view logs, test email, scheduler status."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.alert_rule import AlertRule
from app.models.user import User
from app.schemas.notifications import (
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
    ConditionType,
    DeliveryStatus,
    LogFilters,
    NotificationLogResponse,
    PaginatedLogs,
)
from app.services.auth_service import get_current_user
from app.services.background_scheduler import scheduler
from app.services.notification_service import (
    create_rule,
    delete_rule,
    get_notification_logs,
    get_rule_by_id,
    get_rules,
    update_rule,
)
from app.services.smtp_dispatcher import send_test_email

logger = logging.getLogger(__name__)
router = APIRouter(tags=["notifications"])


# ---------------------------------------------------------------------------
# Helper: convert AlertRule ORM model to response schema
# ---------------------------------------------------------------------------


def _rule_to_response(rule: AlertRule) -> AlertRuleResponse:
    """Convert an AlertRule ORM instance to an AlertRuleResponse schema."""
    try:
        recipients = json.loads(rule.recipients)
    except (json.JSONDecodeError, TypeError):
        recipients = []

    return AlertRuleResponse(
        id=rule.id,
        name=rule.name,
        route_id=rule.route_id,
        route_name=rule.route_name,
        condition_type=ConditionType(rule.condition_type),
        threshold=rule.threshold,
        recipients=recipients,
        cooldown_seconds=rule.cooldown_seconds,
        enabled=rule.enabled,
        health_check_url=rule.health_check_url,
        health_check_interval=rule.health_check_interval,
        health_check_failures_threshold=rule.health_check_failures_threshold,
        notify_controlm=rule.notify_controlm,
        critical=rule.critical,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


# ---------------------------------------------------------------------------
# Alert Rule CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/notifications/rules", response_model=list[AlertRuleResponse])
def list_rules(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    enabled_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List alert rules with pagination. Max 100 rules per page."""
    rules = get_rules(db, enabled_only=enabled_only, page=page, page_size=page_size)
    return [_rule_to_response(r) for r in rules]


@router.post("/notifications/rules", response_model=AlertRuleResponse, status_code=201)
def create_alert_rule(
    body: AlertRuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new alert rule with validation."""
    try:
        rule = create_rule(body, db)
    except ValueError as exc:
        error_msg = str(exc)
        if "already exists" in error_msg:
            raise HTTPException(status_code=409, detail=error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        else:
            raise HTTPException(status_code=422, detail=error_msg)

    logger.info(
        "Alert rule '%s' created by user '%s'", rule.name, current_user.username
    )
    return _rule_to_response(rule)


@router.get("/notifications/rules/{rule_id}", response_model=AlertRuleResponse)
def get_single_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single alert rule by ID."""
    rule = get_rule_by_id(rule_id, db)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return _rule_to_response(rule)


@router.put("/notifications/rules/{rule_id}", response_model=AlertRuleResponse)
def update_alert_rule(
    rule_id: int,
    body: AlertRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing alert rule."""
    try:
        rule = update_rule(rule_id, body, db)
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        elif "already exists" in error_msg:
            raise HTTPException(status_code=409, detail=error_msg)
        else:
            raise HTTPException(status_code=422, detail=error_msg)

    logger.info(
        "Alert rule '%s' (id=%d) updated by user '%s'",
        rule.name,
        rule.id,
        current_user.username,
    )
    return _rule_to_response(rule)


@router.delete("/notifications/rules/{rule_id}", status_code=204)
def delete_alert_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an alert rule by ID."""
    try:
        delete_rule(rule_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    logger.info(
        "Alert rule id=%d deleted by user '%s'", rule_id, current_user.username
    )


@router.patch("/notifications/rules/{rule_id}/toggle", response_model=AlertRuleResponse)
def toggle_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle an alert rule's enabled/disabled status."""
    rule = get_rule_by_id(rule_id, db)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    rule.enabled = not rule.enabled
    db.commit()
    db.refresh(rule)

    status_label = "enabled" if rule.enabled else "disabled"
    logger.info(
        "Alert rule '%s' (id=%d) %s by user '%s'",
        rule.name,
        rule.id,
        status_label,
        current_user.username,
    )
    return _rule_to_response(rule)


# ---------------------------------------------------------------------------
# Notification Logs endpoint
# ---------------------------------------------------------------------------


@router.get("/notifications/logs", response_model=PaginatedLogs)
def list_notification_logs(
    route_id: Optional[str] = Query(None),
    condition_type: Optional[ConditionType] = Query(None),
    delivery_status: Optional[DeliveryStatus] = Query(None),
    date_from: Optional[str] = Query(None, description="ISO 8601 datetime"),
    date_to: Optional[str] = Query(None, description="ISO 8601 datetime"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Query notification logs with filtering and pagination.

    Sorted by timestamp descending. Default 25 entries per page.
    """
    from datetime import datetime

    parsed_date_from = None
    parsed_date_to = None

    if date_from:
        try:
            parsed_date_from = datetime.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid date_from format. Use ISO 8601."
            )

    if date_to:
        try:
            parsed_date_to = datetime.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid date_to format. Use ISO 8601."
            )

    filters = LogFilters(
        route_id=route_id,
        condition_type=condition_type,
        delivery_status=delivery_status,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        page=page,
        page_size=page_size,
    )

    return get_notification_logs(filters, db)


# ---------------------------------------------------------------------------
# Test Email endpoint
# ---------------------------------------------------------------------------


@router.post("/notifications/test-email")
async def test_email(
    recipient: str = Query(..., description="Email address to send test to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a test email to verify SMTP configuration."""
    result = await send_test_email(recipient)

    if result.success:
        logger.info(
            "Test email sent to '%s' by user '%s'", recipient, current_user.username
        )
        return {
            "success": True,
            "message": f"Test email sent successfully to {recipient}",
        }
    else:
        logger.warning(
            "Test email to '%s' failed: %s (requested by '%s')",
            recipient,
            result.error_message,
            current_user.username,
        )
        if "not configured" in (result.error_message or ""):
            raise HTTPException(
                status_code=503,
                detail="Email notifications not configured",
            )
        raise HTTPException(
            status_code=500,
            detail=f"Test email failed: {result.error_message}",
        )


# ---------------------------------------------------------------------------
# Test Fire Alert (preview alert email for a rule)
# ---------------------------------------------------------------------------


@router.post("/notifications/rules/{rule_id}/test-fire")
async def test_fire_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fire a test alert for a rule to preview the email layout.

    Sends a sample alert email using the rule's recipients and condition type,
    with dummy metric values. Does NOT affect cooldown state or notification logs.
    """
    from datetime import datetime, timezone, timedelta
    from app.schemas.notifications import AlertContext
    from app.services.smtp_dispatcher import format_alert_email, send_notification

    rule = get_rule_by_id(rule_id, db)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    try:
        recipients = json.loads(rule.recipients)
    except (json.JSONDecodeError, TypeError):
        recipients = []

    if not recipients:
        raise HTTPException(status_code=422, detail="Rule has no recipients configured")

    # Build sample alert context with dummy data
    now = datetime.now(timezone.utc)
    sample_metrics = {}

    if rule.condition_type == "JWT_FAILURE":
        sample_metrics = {"401_count": 15, "403_count": 5}
    elif rule.condition_type == "UPSTREAM_ERROR":
        sample_metrics = {"502_count": 8, "503_count": 3, "504_count": 2}
    elif rule.condition_type == "HIGH_ERROR_RATE":
        sample_metrics = {"error_rate": 12.5, "total_requests": 1000}
    elif rule.condition_type == "HEALTH_CHECK_FAILURE":
        sample_metrics = {"consecutive_failures": rule.health_check_failures_threshold or 3, "last_error": "Connection timeout after 10s"}
    elif rule.condition_type == "POD_HEALTH":
        sample_metrics = {"unhealthy_pod": "apisix-0", "reason": "CrashLoopBackOff", "restart_count": 5, "total_unhealthy": 1, "unhealthy_pods": ["apisix-0"]}

    context = AlertContext(
        rule_id=rule.id,
        rule_name=rule.name,
        route_id=rule.route_id,
        route_name=rule.route_name or rule.route_id,
        condition_type=rule.condition_type,
        threshold=rule.threshold,
        metric_values=sample_metrics,
        evaluation_window_start=now - timedelta(minutes=5),
        evaluation_window_end=now,
    )

    subject, body_html = format_alert_email(context)
    # Prefix subject to indicate it's a test
    subject = f"[TEST] {subject}"

    result = await send_notification(recipients, subject, body_html)

    if result.success:
        logger.info(
            "Test alert fired for rule '%s' (id=%d) to %s by user '%s'",
            rule.name, rule.id, recipients, current_user.username,
        )
        return {
            "success": True,
            "message": f"Test alert email sent to {', '.join(recipients)}",
            "subject": subject,
            "recipients": recipients,
            "condition_type": rule.condition_type,
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Test alert failed: {result.error_message}",
        )


# ---------------------------------------------------------------------------
# Scheduler Status endpoint
# ---------------------------------------------------------------------------


@router.get("/notifications/status")
def get_scheduler_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the background scheduler status."""
    return {
        "running": scheduler.is_running(),
        "cycle_in_progress": scheduler.is_cycle_in_progress(),
    }
