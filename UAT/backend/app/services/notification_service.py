"""Notification service — orchestrates alert rule evaluation, cooldown management, and dispatch.

Provides CRUD operations for alert rules, cooldown-aware alert triggering,
recovery detection, notification log management, and log purging.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy import desc, and_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.alert_rule import AlertRule
from app.models.notification_log import NotificationLog
from app.schemas.notifications import (
    AlertContext,
    AlertRuleCreate,
    AlertRuleUpdate,
    DeliveryResult,
    DeliveryStatus,
    LogFilters,
    PaginatedLogs,
    NotificationLogResponse,
)
from app.services.smtp_dispatcher import (
    send_notification,
    format_alert_email,
    format_recovery_email,
)
from app.services.controlm_escalation_service import is_critical_pattern

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cooldown logic
# ---------------------------------------------------------------------------


def should_notify(rule_id: int, cooldown_seconds: int, db: Session) -> bool:
    """Check whether a notification should be sent based on cooldown period.

    Returns True if no previous notification exists for this rule, or if the
    cooldown period has elapsed since the last successful notification.

    Args:
        rule_id: The alert rule ID to check.
        cooldown_seconds: The cooldown period in seconds.
        db: Database session.

    Returns:
        True if notification is allowed, False if suppressed by cooldown.
    """
    last_log = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.alert_rule_id == rule_id,
            NotificationLog.delivery_status == DeliveryStatus.SENT.value,
        )
        .order_by(desc(NotificationLog.timestamp))
        .first()
    )

    if last_log is None:
        return True

    elapsed = datetime.now(timezone.utc) - last_log.timestamp.replace(tzinfo=timezone.utc)
    return elapsed.total_seconds() >= cooldown_seconds


# ---------------------------------------------------------------------------
# Alert triggering and recovery
# ---------------------------------------------------------------------------


async def trigger_alert(rule: AlertRule, context: AlertContext, db: Session) -> None:
    """Check cooldown, dispatch alert email, and persist notification log.

    If the cooldown period has not elapsed, the notification is suppressed.
    Otherwise, formats and sends the alert email, then persists the result
    to the notification_logs table.

    Args:
        rule: The alert rule that triggered.
        context: Alert context with metric details.
        db: Database session.
    """
    if not should_notify(rule.id, rule.cooldown_seconds, db):
        logger.debug(
            "Cooldown active for rule %s (id=%d), suppressing notification",
            rule.name,
            rule.id,
        )
        return

    # Enrich context with rule details
    context.rule_id = rule.id
    context.rule_name = rule.name
    context.route_name = rule.route_name or rule.route_id

    # Format email
    subject, body_html = format_alert_email(context)
    recipients = json.loads(rule.recipients)

    # Dispatch email
    result: DeliveryResult = await send_notification(recipients, subject, body_html)

    # Persist notification log
    _persist_log(
        db=db,
        rule=rule,
        context=context,
        subject=subject,
        recipients=recipients,
        result=result,
    )


async def check_recovery(rule: AlertRule, context: AlertContext, db: Session) -> None:
    """Detect threshold return to normal and send recovery email.

    Checks if there was a previous alert for this rule that hasn't been
    followed by a recovery notification. If so, sends a recovery email.

    Only considers alerts from the last 24 hours to prevent stale old
    alerts from triggering confusing recovery emails after pod restarts.

    Args:
        rule: The alert rule to check recovery for.
        context: Alert context with current metric values (is_recovery=True).
        db: Database session.
    """
    # Only consider alerts from the last 24 hours — stale alerts should not
    # trigger recovery emails days/weeks later after a pod restart.
    recovery_window = datetime.now(timezone.utc) - timedelta(hours=24)

    # Check if there was a recent alert (SENT status) without a subsequent recovery
    last_alert = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.alert_rule_id == rule.id,
            NotificationLog.delivery_status == DeliveryStatus.SENT.value,
            ~NotificationLog.subject.like("%RECOVERED%"),
            NotificationLog.timestamp >= recovery_window,
        )
        .order_by(desc(NotificationLog.timestamp))
        .first()
    )

    if last_alert is None:
        # No recent alert, nothing to recover from
        return

    # Check if we already sent a recovery after the last alert
    last_recovery = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.alert_rule_id == rule.id,
            NotificationLog.delivery_status == DeliveryStatus.SENT.value,
            NotificationLog.subject.like("%RECOVERED%"),
            NotificationLog.timestamp > last_alert.timestamp,
        )
        .first()
    )

    if last_recovery is not None:
        # Already sent recovery notification
        return

    # Enrich context
    context.rule_id = rule.id
    context.rule_name = rule.name
    context.route_name = rule.route_name or rule.route_id
    context.is_recovery = True

    # Format and send recovery email
    subject, body_html = format_recovery_email(context)
    recipients = json.loads(rule.recipients)

    result: DeliveryResult = await send_notification(recipients, subject, body_html)

    # Persist notification log
    _persist_log(
        db=db,
        rule=rule,
        context=context,
        subject=subject,
        recipients=recipients,
        result=result,
    )


def _persist_log(
    db: Session,
    rule: AlertRule,
    context: AlertContext,
    subject: str,
    recipients: list[str],
    result: DeliveryResult,
) -> None:
    """Persist a notification log entry after a dispatch attempt.

    Args:
        db: Database session.
        rule: The alert rule.
        context: Alert context.
        subject: Email subject line.
        recipients: List of recipient email addresses.
        result: Delivery result from SMTP dispatcher.
    """
    if result.success:
        status = DeliveryStatus.SENT.value
    else:
        status = DeliveryStatus.FAILED.value

    log_entry = NotificationLog(
        timestamp=datetime.now(timezone.utc),
        alert_rule_id=rule.id,
        route_id=context.route_id,
        route_name=context.route_name,
        condition_type=context.condition_type,
        recipients=json.dumps(recipients),
        subject=subject,
        delivery_status=status,
        error_message=result.error_message,
    )
    db.add(log_entry)
    db.commit()

    logger.info(
        "Notification log persisted: rule=%s, route=%s, status=%s",
        rule.name,
        context.route_id,
        status,
    )


# ---------------------------------------------------------------------------
# CRUD operations for alert rules
# ---------------------------------------------------------------------------


def create_rule(data: AlertRuleCreate, db: Session) -> AlertRule:
    """Create a new alert rule after validating uniqueness and route existence.

    Args:
        data: Validated alert rule creation payload.
        db: Database session.

    Returns:
        The newly created AlertRule.

    Raises:
        ValueError: If the rule name already exists or the route is not found.
    """
    # Check name uniqueness
    existing = db.query(AlertRule).filter(AlertRule.name == data.name).first()
    if existing:
        raise ValueError(f"Rule name already exists: {data.name}")

    # Validate route existence (skip for POD_HEALTH — route_id is a pod name pattern)
    if data.condition_type.value == "POD_HEALTH":
        route_name = data.route_id  # Use the pod pattern as the display name
    else:
        route_name = _validate_route_exists(data.route_id)

    rule = AlertRule(
        name=data.name,
        route_id=data.route_id,
        route_name=route_name,
        condition_type=data.condition_type.value,
        threshold=data.threshold,
        recipients=json.dumps(data.recipients),
        cooldown_seconds=data.cooldown_seconds,
        enabled=data.enabled,
        health_check_url=data.health_check_url,
        health_check_interval=data.health_check_interval,
        health_check_failures_threshold=data.health_check_failures_threshold,
        notify_controlm=data.notify_controlm,
        critical=data.critical,
    )
    db.add(rule)

    # Auto-default critical flag based on route patterns
    if is_critical_pattern(route_name, data.route_id):
        rule.critical = True

    db.commit()
    db.refresh(rule)

    logger.info("Alert rule created: %s (id=%d)", rule.name, rule.id)
    return rule


def update_rule(rule_id: int, data: AlertRuleUpdate, db: Session) -> AlertRule:
    """Update an existing alert rule.

    Args:
        rule_id: ID of the rule to update.
        data: Partial update payload (only non-None fields are applied).
        db: Database session.

    Returns:
        The updated AlertRule.

    Raises:
        ValueError: If the rule is not found, name conflicts, or route is invalid.
    """
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if rule is None:
        raise ValueError("Alert rule not found")

    # Check name uniqueness if name is being changed
    if data.name is not None and data.name != rule.name:
        existing = db.query(AlertRule).filter(AlertRule.name == data.name).first()
        if existing:
            raise ValueError(f"Rule name already exists: {data.name}")
        rule.name = data.name

    # Validate route existence if route_id is being changed
    if data.route_id is not None and data.route_id != rule.route_id:
        # Skip route validation for POD_HEALTH rules (route_id is a pod name pattern)
        current_condition = data.condition_type.value if data.condition_type else rule.condition_type
        if current_condition == "POD_HEALTH":
            route_name = data.route_id
        else:
            route_name = _validate_route_exists(data.route_id)
        rule.route_id = data.route_id
        rule.route_name = route_name

    # Apply other fields
    if data.condition_type is not None:
        rule.condition_type = data.condition_type.value
    if data.threshold is not None:
        rule.threshold = data.threshold
    if data.recipients is not None:
        rule.recipients = json.dumps(data.recipients)
    if data.cooldown_seconds is not None:
        rule.cooldown_seconds = data.cooldown_seconds
    if data.enabled is not None:
        rule.enabled = data.enabled
    if data.health_check_url is not None:
        rule.health_check_url = data.health_check_url
    if data.health_check_interval is not None:
        rule.health_check_interval = data.health_check_interval
    if data.health_check_failures_threshold is not None:
        rule.health_check_failures_threshold = data.health_check_failures_threshold
    if data.notify_controlm is not None:
        rule.notify_controlm = data.notify_controlm
    if data.critical is not None:
        rule.critical = data.critical

    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)

    logger.info("Alert rule updated: %s (id=%d)", rule.name, rule.id)
    return rule


def delete_rule(rule_id: int, db: Session) -> None:
    """Delete an alert rule by ID.

    Args:
        rule_id: ID of the rule to delete.
        db: Database session.

    Raises:
        ValueError: If the rule is not found.
    """
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if rule is None:
        raise ValueError("Alert rule not found")

    db.delete(rule)
    db.commit()

    logger.info("Alert rule deleted: id=%d", rule_id)


def get_rules(
    db: Session,
    enabled_only: bool = False,
    page: int = 1,
    page_size: int = 100,
) -> list[AlertRule]:
    """Retrieve alert rules with optional filtering and pagination.

    Args:
        db: Database session.
        enabled_only: If True, return only enabled rules.
        page: Page number (1-indexed).
        page_size: Maximum rules per page (max 100).

    Returns:
        List of AlertRule objects.
    """
    query = db.query(AlertRule)

    if enabled_only:
        query = query.filter(AlertRule.enabled == True)  # noqa: E712

    query = query.order_by(AlertRule.created_at.desc())

    # Apply pagination
    offset = (page - 1) * page_size
    rules = query.offset(offset).limit(page_size).all()

    return rules


def get_rule_by_id(rule_id: int, db: Session) -> Optional[AlertRule]:
    """Retrieve a single alert rule by ID.

    Args:
        rule_id: ID of the rule.
        db: Database session.

    Returns:
        AlertRule if found, None otherwise.
    """
    return db.query(AlertRule).filter(AlertRule.id == rule_id).first()


# ---------------------------------------------------------------------------
# Notification log queries
# ---------------------------------------------------------------------------


def get_notification_logs(filters: LogFilters, db: Session) -> PaginatedLogs:
    """Query notification logs with filtering and pagination.

    Args:
        filters: Filter criteria including route_id, condition_type,
                 delivery_status, date range, page, and page_size.
        db: Database session.

    Returns:
        PaginatedLogs with items, total count, page, and page_size.
    """
    query = db.query(NotificationLog)

    # Apply filters
    if filters.route_id:
        query = query.filter(NotificationLog.route_id == filters.route_id)
    if filters.condition_type:
        query = query.filter(
            NotificationLog.condition_type == filters.condition_type.value
        )
    if filters.delivery_status:
        query = query.filter(
            NotificationLog.delivery_status == filters.delivery_status.value
        )
    if filters.date_from:
        query = query.filter(NotificationLog.timestamp >= filters.date_from)
    if filters.date_to:
        query = query.filter(NotificationLog.timestamp <= filters.date_to)

    # Get total count before pagination
    total = query.count()

    # Apply ordering and pagination
    query = query.order_by(desc(NotificationLog.timestamp))
    offset = (filters.page - 1) * filters.page_size
    items = query.offset(offset).limit(filters.page_size).all()

    # Convert to response models
    log_responses = []
    for item in items:
        try:
            recipients = json.loads(item.recipients)
        except (json.JSONDecodeError, TypeError):
            recipients = []

        log_responses.append(
            NotificationLogResponse(
                id=item.id,
                timestamp=item.timestamp,
                alert_rule_id=item.alert_rule_id,
                route_id=item.route_id,
                route_name=item.route_name,
                condition_type=item.condition_type,
                recipients=recipients,
                subject=item.subject,
                delivery_status=item.delivery_status,
                error_message=item.error_message,
            )
        )

    return PaginatedLogs(
        items=log_responses,
        total=total,
        page=filters.page,
        page_size=filters.page_size,
    )


# ---------------------------------------------------------------------------
# Log maintenance
# ---------------------------------------------------------------------------


def purge_old_logs(db: Session) -> int:
    """Remove notification logs older than the configured retention period.

    Uses NOTIFICATION_LOG_RETENTION_DAYS from settings to determine the
    cutoff date. All logs with a timestamp before the cutoff are deleted.

    Args:
        db: Database session.

    Returns:
        Number of log records deleted.
    """
    retention_days = settings.NOTIFICATION_LOG_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    count = (
        db.query(NotificationLog)
        .filter(NotificationLog.timestamp < cutoff)
        .delete(synchronize_session="fetch")
    )
    db.commit()

    if count > 0:
        logger.info(
            "Purged %d notification logs older than %d days (cutoff: %s)",
            count,
            retention_days,
            cutoff.isoformat(),
        )

    return count


# ---------------------------------------------------------------------------
# Route validation helper
# ---------------------------------------------------------------------------


def _validate_route_exists(route_id: str) -> str:
    """Validate that a route exists in APISIX and return its name.

    Queries the APISIX Admin API to verify the route ID is valid.

    Args:
        route_id: The APISIX route ID to validate.

    Returns:
        The route name (or route_id if name is not set).

    Raises:
        ValueError: If the route does not exist or cannot be reached.
    """
    try:
        base_url = settings.APISIX_ADMIN_BASE_URL.rstrip("/")
        url = f"{base_url}/apisix/admin/routes/{route_id}"

        with httpx.Client(
            verify=settings.APISIX_ADMIN_VERIFY_SSL,
            timeout=httpx.Timeout(settings.APISIX_ADMIN_TIMEOUT),
        ) as client:
            response = client.get(
                url,
                headers={"X-API-KEY": settings.APISIX_ADMIN_KEY},
            )

        if response.status_code == 404:
            raise ValueError(f"Route not found: {route_id}")

        if response.status_code >= 300:
            logger.warning(
                "APISIX Admin API returned %d when validating route %s",
                response.status_code,
                route_id,
            )
            raise ValueError(f"Route not found: {route_id}")

        # Extract route name from response
        data = response.json()
        # APISIX v3 response format: {"value": {"name": "...", ...}}
        # APISIX v2 response format: {"node": {"value": {"name": "...", ...}}}
        route_value = data.get("value") or data.get("node", {}).get("value", {})
        route_name = route_value.get("name") or route_value.get("uri") or route_id

        return route_name

    except httpx.ConnectError as e:
        logger.error("Cannot reach APISIX Admin API to validate route: %s", e)
        raise ValueError(f"Route not found: {route_id}") from e
    except httpx.TimeoutException as e:
        logger.error("Timeout validating route %s: %s", route_id, e)
        raise ValueError(f"Route not found: {route_id}") from e
