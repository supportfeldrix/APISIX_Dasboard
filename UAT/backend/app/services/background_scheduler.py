"""Background scheduler — manages the periodic evaluation loop within FastAPI lifespan.

Runs evaluation cycles at a configurable interval, fetching Prometheus metrics,
loading enabled alert rules, evaluating each rule against its condition type,
and running health-check probes for HEALTH_CHECK_FAILURE rules.

Also manages the periodic version check task independently of SMTP configuration.

Lifecycle is tied to FastAPI lifespan events (start on startup, stop on shutdown).
The notification scheduler only starts if SMTP configuration is valid (SMTP_HOST is non-empty).
The version check scheduler always starts regardless of SMTP configuration.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.alert_rule import AlertRule
from app.schemas.notifications import AlertContext, ConditionType
from app.services.health_check_prober import HealthCheckProber
from app.services.metrics_evaluator import (
    fetch_route_metrics,
    evaluate_jwt_failure,
    evaluate_upstream_error,
    evaluate_client_error,
    evaluate_high_error_rate,
    MetricsUnavailableError,
)
from app.services.notification_service import (
    trigger_alert,
    check_recovery,
    get_rules,
    purge_old_logs,
)
from app.services.controlm_escalation_service import escalation_service
from app.services.pod_health_evaluator import evaluate_pod_health
from app.services.version_check_service import version_check_service

logger = logging.getLogger(__name__)

# Graceful shutdown timeout in seconds
SHUTDOWN_TIMEOUT_SECONDS = 30.0

# Version check scheduling constants
_VERSION_CHECK_INITIAL_DELAY_SECONDS = 30  # Initial check within 60s of startup
_VERSION_CHECK_RETRY_DELAY_SECONDS = 3600  # Retry after 1 hour on failure
_VERSION_CHECK_MAX_RETRIES = 3  # Max retries per cycle


class BackgroundScheduler:
    """Manages the periodic evaluation loop within FastAPI lifespan.

    The scheduler runs as an asyncio background task, evaluating all enabled
    alert rules at the configured interval. It handles:
    - Overlap detection (skips a cycle if the previous one is still running)
    - Graceful shutdown (waits up to 30s for in-progress evaluations)
    - Error isolation (logs errors and continues to next rule/cycle)
    - SMTP validation (only starts notification loop if SMTP_HOST is configured)
    - Version check scheduling (runs independently of SMTP configuration)
    """

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._version_check_task: asyncio.Task | None = None
        self._running: bool = False
        self._cycle_in_progress: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._prober: HealthCheckProber = HealthCheckProber()
        self._previous_metrics: dict[str, dict[str, float]] = {}
        self._previous_pod_starts: dict[str, str] = {}

    async def start(self) -> None:
        """Start the background scheduler.

        The version check task always starts regardless of SMTP configuration.
        The notification evaluation loop only starts if SMTP_HOST is configured.
        """
        if self._running:
            logger.warning("Background scheduler is already running.")
            return

        self._running = True
        self._stop_event.clear()

        # Always start the version check task (independent of SMTP)
        self._version_check_task = asyncio.create_task(self._version_check_loop())
        logger.info(
            "Version check scheduler started (interval=%dh, initial_delay=%ds).",
            settings.VERSION_CHECK_INTERVAL_HOURS,
            _VERSION_CHECK_INITIAL_DELAY_SECONDS,
        )

        # Only start notification loop if SMTP is configured
        if not settings.SMTP_HOST:
            logger.warning(
                "SMTP_HOST is not configured. "
                "Email notifications disabled — notification scheduler will NOT start."
            )
        else:
            self._task = asyncio.create_task(self._loop())
            logger.info(
                "Notification scheduler started (interval=%ds).",
                settings.NOTIFICATION_EVAL_INTERVAL,
            )

    async def stop(self, timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Stop the background scheduler with graceful shutdown.

        Signals both the notification loop and version check loop to stop,
        and waits up to `timeout` seconds for any in-progress work to complete
        before forcing cancellation.

        Args:
            timeout: Maximum seconds to wait for in-progress evaluation (default 30s).
        """
        if not self._running:
            return

        logger.info("Stopping background scheduler (timeout=%.1fs)...", timeout)
        self._running = False
        self._stop_event.set()

        # Stop notification task
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Notification scheduler did not stop within %.1fs, cancelling.",
                    timeout,
                )
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        # Stop version check task
        if self._version_check_task is not None:
            try:
                await asyncio.wait_for(self._version_check_task, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Version check scheduler did not stop within %.1fs, cancelling.",
                    timeout,
                )
                self._version_check_task.cancel()
                try:
                    await self._version_check_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        self._task = None
        self._version_check_task = None
        logger.info("Background scheduler stopped.")

    def is_running(self) -> bool:
        """Return whether the scheduler is currently running."""
        return self._running

    def is_cycle_in_progress(self) -> bool:
        """Return whether an evaluation cycle is currently in progress."""
        return self._cycle_in_progress

    async def _loop(self) -> None:
        """Main scheduler loop — runs evaluation cycles at the configured interval.

        Sleeps for NOTIFICATION_EVAL_INTERVAL seconds between cycles. If a
        cycle is still in progress when the next one is due, the pending
        cycle is skipped with a warning log.
        """
        interval = settings.NOTIFICATION_EVAL_INTERVAL

        while self._running:
            # Check for overlap — skip if previous cycle still running
            if self._cycle_in_progress:
                logger.warning(
                    "Evaluation cycle overlap detected — previous cycle still running. "
                    "Skipping this cycle."
                )
            else:
                try:
                    await self._run_cycle()
                except Exception as exc:
                    logger.error(
                        "Unhandled exception in evaluation cycle: %s",
                        exc,
                        exc_info=True,
                    )

            # Wait for the interval or until stop is signalled
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=interval,
                )
                # If we get here, stop was signalled
                break
            except asyncio.TimeoutError:
                # Normal timeout — interval elapsed, continue loop
                continue

    async def _version_check_loop(self) -> None:
        """Version check loop — runs version checks at the configured interval.

        Executes an initial check after a short delay (within 60 seconds of startup),
        then schedules recurring checks at VERSION_CHECK_INTERVAL_HOURS intervals.

        Implements retry logic: on failure, retries after 1 hour up to 3 times
        per cycle before waiting for the next scheduled interval.
        """
        # Initial delay before first check (within 60 seconds of startup)
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=_VERSION_CHECK_INITIAL_DELAY_SECONDS,
            )
            # Stop was signalled during initial delay
            return
        except asyncio.TimeoutError:
            # Normal timeout — proceed with initial check
            pass

        while self._running:
            # Run the version check with retry logic
            await self._run_version_check_with_retries()

            # Wait for the configured interval or until stop is signalled
            interval_seconds = settings.VERSION_CHECK_INTERVAL_HOURS * 3600
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=interval_seconds,
                )
                # Stop was signalled
                break
            except asyncio.TimeoutError:
                # Normal timeout — interval elapsed, continue loop
                continue

    async def _run_version_check_with_retries(self) -> None:
        """Execute a version check with retry logic.

        If the check fails (check_successful=False), retries after 1 hour
        up to _VERSION_CHECK_MAX_RETRIES times. If all retries are exhausted,
        the failed result is already persisted by the service.
        """
        for attempt in range(1, _VERSION_CHECK_MAX_RETRIES + 1):
            try:
                logger.info(
                    "Running version check (attempt %d/%d)...",
                    attempt,
                    _VERSION_CHECK_MAX_RETRIES,
                )
                result = await version_check_service.run_check()

                if result.check_successful:
                    logger.info(
                        "Version check succeeded: running=%s, latest=%s, update_available=%s",
                        result.running_version,
                        result.latest_version,
                        result.update_available,
                    )
                    return  # Success — no need to retry

                # Check failed — log and potentially retry
                logger.warning(
                    "Version check failed (attempt %d/%d): %s",
                    attempt,
                    _VERSION_CHECK_MAX_RETRIES,
                    result.error_message or "Unknown error",
                )

            except Exception as exc:
                logger.error(
                    "Unhandled exception during version check (attempt %d/%d): %s",
                    attempt,
                    _VERSION_CHECK_MAX_RETRIES,
                    exc,
                    exc_info=True,
                )

            # If not the last attempt, wait 1 hour before retrying
            if attempt < _VERSION_CHECK_MAX_RETRIES:
                logger.info(
                    "Will retry version check in %d seconds...",
                    _VERSION_CHECK_RETRY_DELAY_SECONDS,
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=_VERSION_CHECK_RETRY_DELAY_SECONDS,
                    )
                    # Stop was signalled during retry wait
                    return
                except asyncio.TimeoutError:
                    # Normal timeout — retry delay elapsed, continue
                    pass

        # All retries exhausted
        logger.error(
            "Version check failed after %d attempts. "
            "Will retry at next scheduled interval (%dh).",
            _VERSION_CHECK_MAX_RETRIES,
            settings.VERSION_CHECK_INTERVAL_HOURS,
        )

    async def _run_cycle(self) -> None:
        """Execute a single evaluation cycle.

        Steps:
        1. Fetch metrics from Prometheus
        2. Load all enabled alert rules from the database
        3. Evaluate each rule against its condition type
        4. Run health-check probes for HEALTH_CHECK_FAILURE rules
        5. Purge old notification logs (once per cycle)

        Errors during individual rule evaluation are logged and do not
        prevent evaluation of subsequent rules.
        """
        self._cycle_in_progress = True
        cycle_start = datetime.now(timezone.utc)
        logger.debug("Evaluation cycle started at %s", cycle_start.isoformat())

        try:
            # Step 1: Fetch metrics from Prometheus
            route_metrics = None
            try:
                route_metrics = fetch_route_metrics()
            except MetricsUnavailableError as exc:
                logger.error(
                    "Metrics unavailable, skipping metric-based evaluations: %s", exc
                )

            # Step 2: Load enabled alert rules
            db = SessionLocal()
            try:
                rules = get_rules(db, enabled_only=True)

                if not rules:
                    logger.debug("No enabled alert rules found, skipping evaluation.")
                    return

                # Step 3 & 4: Evaluate each rule
                for rule in rules:
                    if not self._running:
                        logger.info("Shutdown requested, aborting evaluation cycle.")
                        break

                    try:
                        await self._evaluate_rule(rule, route_metrics, db)
                    except Exception as exc:
                        logger.error(
                            "Error evaluating rule '%s' (id=%d): %s",
                            rule.name,
                            rule.id,
                            exc,
                            exc_info=True,
                        )
                        continue

                # Step 5: Purge old logs (best-effort)
                try:
                    purge_old_logs(db)
                except Exception as exc:
                    logger.error("Error purging old notification logs: %s", exc)

            finally:
                db.close()

        finally:
            self._cycle_in_progress = False
            elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.debug("Evaluation cycle completed in %.2fs", elapsed)

    async def _evaluate_rule(
        self,
        rule: AlertRule,
        route_metrics: dict | None,
        db,
    ) -> None:
        """Evaluate a single alert rule against current metrics or health probes.

        For metric-based conditions (JWT_FAILURE, UPSTREAM_ERROR, HIGH_ERROR_RATE),
        evaluates against the fetched Prometheus metrics. For HEALTH_CHECK_FAILURE,
        runs an active HTTP probe against the configured health-check URL.

        Args:
            rule: The alert rule to evaluate.
            route_metrics: Per-route metrics dict (may be None if fetch failed).
            db: Database session.
        """
        condition = rule.condition_type

        if condition == ConditionType.HEALTH_CHECK_FAILURE.value:
            await self._evaluate_health_check(rule, db)
        elif condition == ConditionType.POD_HEALTH.value:
            await self._evaluate_pod_health(rule, db)
        elif route_metrics is not None:
            await self._evaluate_metric_rule(rule, route_metrics, db)
        else:
            # Metrics unavailable — skip metric-based rules
            logger.debug(
                "Skipping metric-based rule '%s' (id=%d) — metrics unavailable.",
                rule.name,
                rule.id,
            )

    async def _evaluate_metric_rule(
        self,
        rule: AlertRule,
        route_metrics: dict,
        db,
    ) -> None:
        """Evaluate a metric-based alert rule (JWT_FAILURE, UPSTREAM_ERROR, HIGH_ERROR_RATE).

        For UPSTREAM_ERROR and CLIENT_ERROR, uses delta-based evaluation: only alerts
        when NEW errors appear since the last evaluation cycle. Sends recovery when
        no new errors appear AND new 2xx requests have come in.

        For JWT_FAILURE and HIGH_ERROR_RATE, uses the original cumulative logic.

        Args:
            rule: The alert rule to evaluate.
            route_metrics: Per-route metrics dict from Prometheus.
            db: Database session.
        """
        condition = rule.condition_type
        threshold = rule.threshold

        # Resolve the metrics lookup key: Prometheus may use route name instead
        # of numeric route ID as the 'route' label (depends on APISIX config).
        # Try route_id first, fall back to route_name.
        route_id = rule.route_id
        if route_id not in route_metrics and rule.route_name:
            route_id = rule.route_name

        logger.info(
            "[METRIC_RULE] rule='%s' condition=%s resolved_route_id='%s' found_in_metrics=%s",
            rule.name, condition, route_id, route_id in route_metrics,
        )

        if condition == ConditionType.UPSTREAM_ERROR.value:
            # Delta-based evaluation: only alert on NEW 5xx errors
            metrics = route_metrics.get(route_id)
            if metrics is not None:
                # Calculate current 5xx total
                current_5xx = 0.0
                fivexx_breakdown = {}
                for code, count in metrics.items():
                    try:
                        code_int = int(code)
                    except (ValueError, TypeError):
                        continue
                    if 500 <= code_int <= 599:
                        current_5xx += count
                        fivexx_breakdown[code] = count

                # Get previous 5xx total for this route
                prev_metrics = self._previous_metrics.get(route_id, {})
                previous_5xx = 0.0
                for code, count in prev_metrics.items():
                    try:
                        code_int = int(code)
                    except (ValueError, TypeError):
                        continue
                    if 500 <= code_int <= 599:
                        previous_5xx += count

                # Calculate delta (new errors since last check)
                delta_5xx = current_5xx - previous_5xx

                # Store current metrics for next cycle comparison
                self._previous_metrics[route_id] = dict(metrics)

                # First cycle after pod restart: _previous_metrics was empty so
                # prev_metrics is {}. Treat this as a baseline — store metrics but
                # do NOT alert. This prevents false alerts from cumulative counters.
                if not prev_metrics:
                    logger.debug(
                        "UPSTREAM_ERROR baseline established for route '%s' "
                        "(current_5xx=%.0f). No alert on first cycle.",
                        route_id, current_5xx,
                    )
                    return

                if delta_5xx >= threshold:
                    # New 5xx errors detected — trigger alert
                    now = datetime.now(timezone.utc)
                    context = AlertContext(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        route_id=route_id,
                        route_name=rule.route_name or route_id,
                        condition_type=ConditionType.UPSTREAM_ERROR,
                        metric_values={
                            "5xx_breakdown": fivexx_breakdown,
                            "total_upstream_errors": current_5xx,
                            "new_errors": delta_5xx,
                        },
                        threshold=threshold,
                        evaluation_window_start=now - timedelta(minutes=5),
                        evaluation_window_end=now,
                    )
                    await trigger_alert(rule, context, db)
                    await escalation_service.handle_alert_triggered(rule, context, db)
                else:
                    # No new 5xx — check if traffic is flowing (new 2xx = service recovered)
                    current_2xx = sum(
                        count for code, count in metrics.items()
                        if code.startswith("2")
                    )
                    previous_2xx = sum(
                        count for code, count in prev_metrics.items()
                        if code.startswith("2")
                    )
                    delta_2xx = current_2xx - previous_2xx

                    if delta_2xx > 0:
                        # Traffic flowing successfully, no new errors — send recovery
                        recovery_context = AlertContext(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            route_id=route_id,
                            route_name=rule.route_name or route_id,
                            condition_type=ConditionType.UPSTREAM_ERROR.value,
                            metric_values={"new_2xx": delta_2xx, "new_5xx": 0},
                            threshold=threshold,
                            is_recovery=True,
                        )
                        await check_recovery(rule, recovery_context, db)
                        await escalation_service.handle_recovery(rule, db)
            return

        if condition == ConditionType.CLIENT_ERROR.value:
            # Delta-based evaluation: only alert on NEW 4xx errors.
            # Uses a HIGH-WATER MARK to avoid false positives from the metrics
            # service load-balancing across multiple APISIX pods (each pod has
            # its own independent counters — alternating between pods causes
            # the observed count to jump up/down, creating false deltas).
            metrics = route_metrics.get(route_id)
            if metrics is not None:
                # Calculate current 4xx total
                current_4xx = 0.0
                fourxx_breakdown = {}
                for code, count in metrics.items():
                    try:
                        code_int = int(code)
                    except (ValueError, TypeError):
                        continue
                    if 400 <= code_int <= 499:
                        current_4xx += count
                        fourxx_breakdown[code] = count

                # Get the high-water mark (maximum 4xx count ever seen).
                # Only fire when current exceeds the previous maximum —
                # this means genuinely NEW errors occurred.
                client_error_key = f"__client_error__{route_id}"
                prev_data = self._previous_metrics.get(client_error_key, {})
                hwm_4xx = prev_data.get("__hwm_4xx__", 0.0)

                # Delta is only positive when we exceed the historical max
                delta_4xx = current_4xx - hwm_4xx

                # Update the high-water mark (never decreases)
                new_hwm = max(hwm_4xx, current_4xx)
                self._previous_metrics[client_error_key] = {
                    "__hwm_4xx__": new_hwm,
                    **{k: v for k, v in metrics.items()},
                }

                # First cycle after pod restart: prev_data is empty (no hwm stored).
                # Treat this as a baseline — store the hwm but do NOT alert.
                if not prev_data:
                    logger.debug(
                        "CLIENT_ERROR baseline established for route '%s' "
                        "(current_4xx=%.0f, hwm=%.0f). No alert on first cycle.",
                        route_id, current_4xx, new_hwm,
                    )
                    return

                # Log for debugging
                if current_4xx > 0:
                    logger.info(
                        "[CLIENT_ERROR] route=%s current_4xx=%.0f hwm=%.0f delta=%.0f threshold=%d",
                        route_id, current_4xx, hwm_4xx, delta_4xx, threshold,
                    )

                if delta_4xx >= threshold:
                    # New 4xx errors detected — trigger alert
                    now = datetime.now(timezone.utc)
                    context = AlertContext(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        route_id=route_id,
                        route_name=rule.route_name or route_id,
                        condition_type=ConditionType.CLIENT_ERROR,
                        metric_values={
                            "4xx_breakdown": fourxx_breakdown,
                            "total_client_errors": current_4xx,
                            "new_errors": delta_4xx,
                        },
                        threshold=threshold,
                        evaluation_window_start=now - timedelta(minutes=5),
                        evaluation_window_end=now,
                    )
                    await trigger_alert(rule, context, db)
                    await escalation_service.handle_alert_triggered(rule, context, db)
                else:
                    # No new 4xx above high-water mark — send recovery if 2xx traffic is flowing
                    current_2xx = sum(
                        count for code, count in metrics.items()
                        if code.startswith("2")
                    )

                    if current_2xx > 0:
                        # Traffic flowing successfully, no new errors — send recovery
                        recovery_context = AlertContext(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            route_id=route_id,
                            route_name=rule.route_name or route_id,
                            condition_type=ConditionType.CLIENT_ERROR.value,
                            metric_values={"current_2xx": current_2xx, "new_4xx": 0},
                            threshold=threshold,
                            is_recovery=True,
                        )
                        await check_recovery(rule, recovery_context, db)
                        await escalation_service.handle_recovery(rule, db)
            return

        context: AlertContext | None = None

        if condition == ConditionType.JWT_FAILURE.value:
            context = evaluate_jwt_failure(route_metrics, route_id, threshold)
        elif condition == ConditionType.HIGH_ERROR_RATE.value:
            context = evaluate_high_error_rate(route_metrics, route_id, threshold)
        else:
            logger.warning(
                "Unknown condition type '%s' for rule '%s' (id=%d)",
                condition,
                rule.name,
                rule.id,
            )
            return

        if context is not None:
            # Threshold breached — trigger alert
            context.rule_id = rule.id
            context.rule_name = rule.name
            context.route_name = rule.route_name or rule.route_id
            await trigger_alert(rule, context, db)
            await escalation_service.handle_alert_triggered(rule, context, db)
        else:
            # Threshold not breached — no recovery logic for JWT/HIGH_ERROR_RATE
            pass

    async def _evaluate_health_check(self, rule: AlertRule, db) -> None:
        """Evaluate a HEALTH_CHECK_FAILURE rule by probing the configured URL.

        Sends an HTTP GET to the rule's health_check_url and updates the
        probe state. Triggers an alert if the consecutive failure threshold
        is reached, or a recovery notification if the route recovers.

        Args:
            rule: The alert rule with health-check configuration.
            db: Database session.
        """
        url = rule.health_check_url
        if not url:
            logger.debug(
                "Rule '%s' (id=%d) has no health_check_url configured, skipping.",
                rule.name,
                rule.id,
            )
            return

        failure_threshold = rule.health_check_failures_threshold or 3

        # Probe the route
        result = await self._prober.probe_route(rule.route_id, url)

        # Update state and check for alert/recovery
        context = self._prober.update_state(
            route_id=rule.route_id,
            result=result,
            failure_threshold=failure_threshold,
            route_name=rule.route_name or rule.route_id,
            rule_id=rule.id,
            rule_name=rule.name,
        )

        if context is not None:
            if context.is_recovery:
                await check_recovery(rule, context, db)
                await escalation_service.handle_recovery(rule, db)
            else:
                await trigger_alert(rule, context, db)
                await escalation_service.handle_alert_triggered(rule, context, db)


    async def _evaluate_pod_health(self, rule: AlertRule, db) -> None:
        """Evaluate a POD_HEALTH rule by checking pod statuses.

        Uses the route_id field as a pod name pattern filter.
        Triggers an alert if any matching pod is unhealthy (OOMKilled,
        CrashLoopBackOff, restart count exceeds threshold, or pod recreated).
        Sends a recovery email once pods are back to running/ready state.

        Pod recreation detection: tracks pod startTime between evaluation cycles.
        If a pod's startTime changes, it was deleted and recreated (e.g. during a
        StatefulSet rolling update). This fires an alert so operators are notified.

        Args:
            rule: The alert rule with POD_HEALTH condition.
            db: Database session.
        """
        context, current_pod_starts = evaluate_pod_health(
            route_id=rule.route_id,
            threshold=rule.threshold,
            previous_pod_starts=self._previous_pod_starts,
        )

        # Always update the stored pod start times for the next cycle
        self._previous_pod_starts = current_pod_starts

        if context is not None:
            # Pod is unhealthy — check if it's NOT ready (actively crashing)
            # or just has a high restart count but is running fine
            is_ready = context.metric_values.get("reason", "").endswith("- now running")

            if not is_ready:
                # Pod is actively unhealthy (not ready, CrashLoopBackOff, etc.)
                context.rule_id = rule.id
                context.rule_name = rule.name
                await trigger_alert(rule, context, db)
                await escalation_service.handle_alert_triggered(rule, context, db)
            else:
                # Pod has restarts but IS running and ready — send recovery if last was alert
                from app.schemas.notifications import AlertContext, ConditionType
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                recovery_context = AlertContext(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    route_id=rule.route_id,
                    route_name=rule.route_name or rule.route_id,
                    condition_type=ConditionType.POD_HEALTH,
                    metric_values=context.metric_values,
                    threshold=rule.threshold,
                    evaluation_window_start=now,
                    evaluation_window_end=now,
                    is_recovery=True,
                )
                await check_recovery(rule, recovery_context, db)
                await escalation_service.handle_recovery(rule, db)
        else:
            # All pods healthy (restartCount below threshold) — send recovery if needed
            from app.schemas.notifications import AlertContext, ConditionType
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            recovery_context = AlertContext(
                rule_id=rule.id,
                rule_name=rule.name,
                route_id=rule.route_id,
                route_name=rule.route_name or rule.route_id,
                condition_type=ConditionType.POD_HEALTH,
                metric_values={
                    "unhealthy_pod": "None",
                    "reason": "All pods healthy",
                    "restart_count": 0,
                    "total_unhealthy": 0,
                    "unhealthy_pods": [],
                },
                threshold=rule.threshold,
                evaluation_window_start=now,
                evaluation_window_end=now,
                is_recovery=True,
            )
            await check_recovery(rule, recovery_context, db)
            await escalation_service.handle_recovery(rule, db)


# Module-level singleton instance
scheduler = BackgroundScheduler()
