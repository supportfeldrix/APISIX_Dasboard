"""ControlM Escalation Service — manages escalation lifecycle: decision, grace period, acknowledgment, recovery.

Coordinates the decision logic for when to write trigger files to the ControlM landing zone,
manages async grace period timers, handles operator acknowledgments, and tracks escalation state.
Integrates with BackgroundScheduler via handle_alert_triggered() and handle_recovery() methods.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.alert_rule import AlertRule
from app.models.controlm_settings import ControlMSettings
from app.models.escalation_log import EscalationLog
from app.models.escalation_state import EscalationState
from app.schemas.notifications import AlertContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Critical pattern matching
# ---------------------------------------------------------------------------

CRITICAL_PATTERNS = [
    "realtimewsprovider",
    "realtimescreening",
    "rts",
    "actimize",
    "actone",
    "rcm",
]


def is_critical_pattern(route_name: str, route_id: str) -> bool:
    """Check if route name or ID matches known critical patterns."""
    combined = f"{route_name or ''} {route_id or ''}".lower()
    return any(p in combined for p in CRITICAL_PATTERNS)


# ---------------------------------------------------------------------------
# EscalationService
# ---------------------------------------------------------------------------


class EscalationService:
    """Manages escalation lifecycle: decision, grace period, acknowledgment, recovery."""

    def __init__(self):
        self._pending_tasks: dict[int, asyncio.Task] = {}  # rule_id -> grace period task
        self._lock = asyncio.Lock()  # protects _pending_tasks dict

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_alert_triggered(
        self, rule: AlertRule, context: AlertContext, db: Session
    ) -> None:
        """Called from BackgroundScheduler when an alert rule triggers.

        Decides whether to escalate immediately, start a grace period countdown,
        or skip escalation entirely based on global/per-rule configuration.

        Args:
            rule: The alert rule that triggered.
            context: Alert context with metric details.
            db: Database session.
        """
        # Check global ControlM toggle
        settings_row = db.query(ControlMSettings).filter(ControlMSettings.id == 1).first()
        if settings_row is None or not settings_row.controlm_enabled:
            logger.debug(
                "ControlM escalation disabled globally, skipping rule '%s' (id=%d)",
                rule.name,
                rule.id,
            )
            return

        # Check per-rule toggle
        if not rule.notify_controlm:
            logger.debug(
                "ControlM escalation disabled for rule '%s' (id=%d), skipping",
                rule.name,
                rule.id,
            )
            return

        # Check if there's already an active escalation cycle for this rule
        esc_state = (
            db.query(EscalationState)
            .filter(EscalationState.rule_id == rule.id)
            .first()
        )
        if esc_state is not None and esc_state.state != "idle":
            logger.debug(
                "Escalation already active for rule '%s' (id=%d, state=%s), skipping",
                rule.name,
                rule.id,
                esc_state.state,
            )
            return

        # Determine effective grace period
        grace_period = self._get_effective_grace_period(rule, db)

        if grace_period == 0:
            await self._escalate_immediately(rule, context, db)
        else:
            await self._start_grace_period(rule, context, db)

    async def handle_recovery(self, rule: AlertRule, db: Session) -> None:
        """Called from BackgroundScheduler when a rule recovers.

        If the rule was escalated, writes a recovery file. If pending,
        cancels the grace period timer.

        Args:
            rule: The alert rule that recovered.
            db: Database session.
        """
        esc_state = (
            db.query(EscalationState)
            .filter(EscalationState.rule_id == rule.id)
            .first()
        )

        if esc_state is None or esc_state.state == "idle":
            return

        if esc_state.state == "escalated":
            # Write recovery file
            from app.services.controlm_trigger_writer import TriggerFileWriter

            writer = TriggerFileWriter()
            now = datetime.now(timezone.utc)
            success, file_path_or_error = writer.write_recovery_file(rule, now, db)

            if success:
                self._log_event(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    event_type="recovery_file_written",
                    file_path=file_path_or_error,
                    db=db,
                )
            else:
                logger.error(
                    "Failed to write recovery file for rule '%s' (id=%d): %s",
                    rule.name,
                    rule.id,
                    file_path_or_error,
                )

            # Reset state to idle
            esc_state.state = "idle"
            esc_state.grace_started_at = None
            esc_state.grace_expires_at = None
            esc_state.escalated_at = None
            esc_state.trigger_file = None
            esc_state.failure_message = None
            db.merge(esc_state)
            db.commit()

        elif esc_state.state == "pending":
            # Cancel pending grace period
            await self._cancel_pending(rule.id, "recovery_cancelled_pending", db)
            self._log_event(
                rule_id=rule.id,
                rule_name=rule.name,
                event_type="recovery_cancelled_pending",
                db=db,
            )

    async def acknowledge(
        self, rule_id: int, username: str, db: Session
    ) -> tuple[bool, str]:
        """Operator acknowledges a pending escalation.

        Cancels the grace period timer and resets the escalation state to idle.

        Args:
            rule_id: The alert rule ID to acknowledge.
            username: The operator username performing the acknowledgment.
            db: Database session.

        Returns:
            Tuple of (success, message).
        """
        esc_state = (
            db.query(EscalationState)
            .filter(EscalationState.rule_id == rule_id)
            .first()
        )

        if esc_state is None or esc_state.state == "idle":
            return (False, "No pending escalation")

        if esc_state.state == "escalated":
            return (False, "Escalation has already occurred")

        # State is 'pending' — cancel it
        async with self._lock:
            task = self._pending_tasks.pop(rule_id, None)
            if task is not None and not task.done():
                task.cancel()

        # Update state to idle
        esc_state.state = "idle"
        esc_state.grace_started_at = None
        esc_state.grace_expires_at = None
        esc_state.escalated_at = None
        esc_state.trigger_file = None
        esc_state.failure_message = None
        db.merge(esc_state)
        db.commit()

        # Log acknowledgment
        self._log_event(
            rule_id=rule_id,
            rule_name=self._get_rule_name(rule_id, db),
            event_type="acknowledged",
            username=username,
            db=db,
        )

        rule_name = self._get_rule_name(rule_id, db)
        return (True, f"Escalation acknowledged and cancelled for rule '{rule_name}'")

    def get_escalation_status(self, rule_id: int, db: Session) -> dict:
        """Returns current escalation state for a single rule.

        Args:
            rule_id: The alert rule ID.
            db: Database session.

        Returns:
            Dict with state info and timing details.
        """
        esc_state = (
            db.query(EscalationState)
            .filter(EscalationState.rule_id == rule_id)
            .first()
        )

        if esc_state is None:
            return {"state": "idle"}

        result: dict = {"state": esc_state.state}

        if esc_state.state == "pending":
            now = datetime.now(timezone.utc)
            if esc_state.grace_expires_at:
                expires_at = esc_state.grace_expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                remaining = (expires_at - now).total_seconds()
                result["grace_remaining_seconds"] = max(0, int(remaining))
            else:
                result["grace_remaining_seconds"] = 0
            result["grace_started_at"] = (
                esc_state.grace_started_at.isoformat()
                if esc_state.grace_started_at
                else None
            )

        elif esc_state.state == "escalated":
            result["escalated_at"] = (
                esc_state.escalated_at.isoformat()
                if esc_state.escalated_at
                else None
            )
            result["trigger_file"] = esc_state.trigger_file

        return result

    def get_all_statuses(self, db: Session) -> dict[int, dict]:
        """Returns escalation states for all rules with non-idle state.

        Args:
            db: Database session.

        Returns:
            Dict mapping rule_id to status dict.
        """
        rows = (
            db.query(EscalationState)
            .filter(EscalationState.state != "idle")
            .all()
        )

        result: dict[int, dict] = {}
        now = datetime.now(timezone.utc)

        for row in rows:
            status: dict = {"state": row.state}

            if row.state == "pending":
                if row.grace_expires_at:
                    expires_at = row.grace_expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    remaining = (expires_at - now).total_seconds()
                    status["grace_remaining_seconds"] = max(0, int(remaining))
                else:
                    status["grace_remaining_seconds"] = 0
                status["grace_started_at"] = (
                    row.grace_started_at.isoformat() if row.grace_started_at else None
                )

            elif row.state == "escalated":
                status["escalated_at"] = (
                    row.escalated_at.isoformat() if row.escalated_at else None
                )
                status["trigger_file"] = row.trigger_file

            result[row.rule_id] = status

        return result

    async def restore_state_on_startup(self) -> None:
        """Load persisted escalation state from DB, restart pending grace periods.

        Called during application startup (FastAPI lifespan). For rules that
        were in 'pending' state when the app shut down:
        - If grace period has already expired: escalate immediately.
        - If grace period still has time remaining: start a new asyncio task.
        """
        db = SessionLocal()
        try:
            pending_rows = (
                db.query(EscalationState)
                .filter(EscalationState.state == "pending")
                .all()
            )

            if not pending_rows:
                logger.info("No pending escalation states to restore on startup.")
                return

            now = datetime.now(timezone.utc)

            for row in pending_rows:
                rule_id = row.rule_id
                expires_at = row.grace_expires_at

                if expires_at is None:
                    # No expiry set — escalate immediately as a safety measure
                    logger.warning(
                        "Pending escalation for rule_id=%d has no grace_expires_at, escalating immediately.",
                        rule_id,
                    )
                    await self._escalate_on_startup(rule_id, db)
                    continue

                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                remaining = (expires_at - now).total_seconds()

                if remaining <= 0:
                    # Grace period already expired — escalate immediately
                    logger.info(
                        "Grace period expired during downtime for rule_id=%d, escalating now.",
                        rule_id,
                    )
                    await self._escalate_on_startup(rule_id, db)
                else:
                    # Restart the grace period timer for remaining time
                    logger.info(
                        "Restarting grace period for rule_id=%d (%.1fs remaining).",
                        rule_id,
                        remaining,
                    )
                    task = asyncio.create_task(
                        self._grace_period_worker(rule_id, remaining)
                    )
                    async with self._lock:
                        self._pending_tasks[rule_id] = task

        except Exception as exc:
            logger.error(
                "Error restoring escalation state on startup: %s", exc, exc_info=True
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    async def _start_grace_period(
        self, rule: AlertRule, context: AlertContext, db: Session
    ) -> None:
        """Start an asyncio task for the grace period countdown."""
        grace_seconds = self._get_effective_grace_period(rule, db)
        now = datetime.now(timezone.utc)
        grace_expires_at = now + timedelta(seconds=grace_seconds)

        # Build failure message from context
        failure_message = self._build_failure_message(context)

        # Upsert EscalationState row
        esc_state = EscalationState(
            rule_id=rule.id,
            state="pending",
            grace_started_at=now,
            grace_expires_at=grace_expires_at,
            escalated_at=None,
            trigger_file=None,
            failure_message=failure_message,
        )
        db.merge(esc_state)
        db.commit()

        # Create asyncio task for the grace period
        task = asyncio.create_task(
            self._grace_period_worker(rule.id, grace_seconds)
        )
        async with self._lock:
            self._pending_tasks[rule.id] = task

        logger.info(
            "Grace period started for rule '%s' (id=%d): %d seconds, expires at %s",
            rule.name,
            rule.id,
            grace_seconds,
            grace_expires_at.isoformat(),
        )

    async def _grace_period_worker(self, rule_id: int, grace_seconds: float) -> None:
        """Worker task that waits for the grace period then triggers escalation."""
        try:
            await asyncio.sleep(grace_seconds)
            await self._on_grace_period_expired(rule_id)
        except asyncio.CancelledError:
            logger.debug(
                "Grace period task cancelled for rule_id=%d (acknowledged or recovered).",
                rule_id,
            )

    async def _on_grace_period_expired(self, rule_id: int) -> None:
        """Grace period expired — write trigger file and update state."""
        db = SessionLocal()
        try:
            # Verify still in pending state (might have been cancelled)
            esc_state = (
                db.query(EscalationState)
                .filter(EscalationState.rule_id == rule_id)
                .first()
            )

            if esc_state is None or esc_state.state != "pending":
                logger.debug(
                    "Grace period expired for rule_id=%d but state is no longer pending, skipping.",
                    rule_id,
                )
                return

            # Get the rule
            rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
            if rule is None:
                logger.warning(
                    "Rule_id=%d not found when grace period expired, resetting state.",
                    rule_id,
                )
                esc_state.state = "idle"
                db.merge(esc_state)
                db.commit()
                return

            # Log grace period expired event
            self._log_event(
                rule_id=rule_id,
                rule_name=rule.name,
                event_type="grace_period_expired",
                db=db,
            )

            # Write trigger file
            from app.services.controlm_trigger_writer import TriggerFileWriter

            writer = TriggerFileWriter()
            now = datetime.now(timezone.utc)

            # Build context from stored failure_message
            context = AlertContext(
                rule_id=rule.id,
                rule_name=rule.name,
                route_id=rule.route_id,
                route_name=rule.route_name or rule.route_id,
                condition_type=rule.condition_type,
                metric_values={},
                threshold=rule.threshold,
            )

            success, file_path_or_error = writer.write_trigger_file(
                rule, context, now, db
            )

            if success:
                # Update state to escalated
                esc_state.state = "escalated"
                esc_state.escalated_at = now
                esc_state.trigger_file = file_path_or_error
                db.merge(esc_state)
                db.commit()

                self._log_event(
                    rule_id=rule_id,
                    rule_name=rule.name,
                    event_type="trigger_file_written",
                    file_path=file_path_or_error,
                    db=db,
                )
            else:
                logger.error(
                    "Failed to write trigger file for rule '%s' (id=%d) after grace period: %s",
                    rule.name,
                    rule_id,
                    file_path_or_error,
                )
                self._log_event(
                    rule_id=rule_id,
                    rule_name=rule.name,
                    event_type="trigger_file_failed",
                    error_msg=file_path_or_error[:500] if file_path_or_error else None,
                    db=db,
                )

        except Exception as exc:
            logger.error(
                "Error in _on_grace_period_expired for rule_id=%d: %s",
                rule_id,
                exc,
                exc_info=True,
            )
        finally:
            # Remove from pending tasks
            async with self._lock:
                self._pending_tasks.pop(rule_id, None)
            db.close()

    async def _escalate_immediately(
        self, rule: AlertRule, context: AlertContext, db: Session
    ) -> None:
        """Write trigger file immediately (critical or grace=0)."""
        from app.services.controlm_trigger_writer import TriggerFileWriter

        writer = TriggerFileWriter()
        now = datetime.now(timezone.utc)

        success, file_path_or_error = writer.write_trigger_file(rule, context, now, db)

        failure_message = self._build_failure_message(context)

        if success:
            # Upsert EscalationState to 'escalated'
            esc_state = EscalationState(
                rule_id=rule.id,
                state="escalated",
                grace_started_at=None,
                grace_expires_at=None,
                escalated_at=now,
                trigger_file=file_path_or_error,
                failure_message=failure_message,
            )
            db.merge(esc_state)
            db.commit()

            self._log_event(
                rule_id=rule.id,
                rule_name=rule.name,
                event_type="trigger_file_written",
                file_path=file_path_or_error,
                db=db,
            )
            logger.info(
                "Immediate escalation triggered for rule '%s' (id=%d): %s",
                rule.name,
                rule.id,
                file_path_or_error,
            )
        else:
            logger.error(
                "Failed to write trigger file for rule '%s' (id=%d): %s",
                rule.name,
                rule.id,
                file_path_or_error,
            )
            self._log_event(
                rule_id=rule.id,
                rule_name=rule.name,
                event_type="trigger_file_failed",
                error_msg=file_path_or_error[:500] if file_path_or_error else None,
                db=db,
            )

    async def _cancel_pending(self, rule_id: int, reason: str, db: Session) -> None:
        """Cancel a pending grace period task."""
        async with self._lock:
            task = self._pending_tasks.pop(rule_id, None)
            if task is not None and not task.done():
                task.cancel()

        # Update EscalationState to idle
        esc_state = (
            db.query(EscalationState)
            .filter(EscalationState.rule_id == rule_id)
            .first()
        )
        if esc_state is not None:
            esc_state.state = "idle"
            esc_state.grace_started_at = None
            esc_state.grace_expires_at = None
            esc_state.escalated_at = None
            esc_state.trigger_file = None
            esc_state.failure_message = None
            db.merge(esc_state)
            db.commit()

        logger.info(
            "Pending escalation cancelled for rule_id=%d, reason=%s",
            rule_id,
            reason,
        )

    def _get_effective_grace_period(self, rule: AlertRule, db: Session) -> int:
        """Returns 0 if critical flag set, otherwise global grace_period setting."""
        if rule.critical:
            return 0

        settings_row = db.query(ControlMSettings).filter(ControlMSettings.id == 1).first()
        if settings_row is None:
            return 0

        return settings_row.grace_period or 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _escalate_on_startup(self, rule_id: int, db: Session) -> None:
        """Escalate a rule during startup (grace period expired during downtime)."""
        rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
        if rule is None:
            logger.warning(
                "Rule_id=%d not found during startup escalation, resetting state.",
                rule_id,
            )
            esc_state = (
                db.query(EscalationState)
                .filter(EscalationState.rule_id == rule_id)
                .first()
            )
            if esc_state:
                esc_state.state = "idle"
                db.merge(esc_state)
                db.commit()
            return

        # Build a minimal context from stored state
        esc_state = (
            db.query(EscalationState)
            .filter(EscalationState.rule_id == rule_id)
            .first()
        )

        context = AlertContext(
            rule_id=rule.id,
            rule_name=rule.name,
            route_id=rule.route_id,
            route_name=rule.route_name or rule.route_id,
            condition_type=rule.condition_type,
            metric_values={},
            threshold=rule.threshold,
        )

        await self._escalate_immediately(rule, context, db)

    def _build_failure_message(self, context: AlertContext) -> str:
        """Build a failure message string from context."""
        parts = [
            f"Condition: {context.condition_type}",
            f"Route: {context.route_name or context.route_id}",
            f"Threshold: {context.threshold}",
        ]
        if context.metric_values:
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in context.metric_values.items()
            )
            parts.append(f"Metrics: {metrics_str}")
        return "; ".join(parts)

    def _get_rule_name(self, rule_id: int, db: Session) -> str:
        """Get rule name by ID, returns 'Unknown' if not found."""
        rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
        return rule.name if rule else "Unknown"

    def _log_event(
        self,
        rule_id: int,
        rule_name: str,
        event_type: str,
        db: Session,
        file_path: str | None = None,
        username: str | None = None,
        error_msg: str | None = None,
    ) -> None:
        """Write an entry to the escalation audit log."""
        log_entry = EscalationLog(
            rule_id=rule_id,
            rule_name=rule_name,
            event_type=event_type,
            file_path=file_path,
            username=username,
            error_msg=error_msg,
            created_at=datetime.now(timezone.utc),
        )
        db.add(log_entry)
        db.commit()

        logger.info(
            "Escalation event logged: rule='%s' (id=%d), event=%s",
            rule_name,
            rule_id,
            event_type,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

escalation_service = EscalationService()
