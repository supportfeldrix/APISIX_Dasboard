"""Health check prober — active HTTP probing for route upstream availability.

Sends periodic HTTP GET requests to configured route health-check URLs and
tracks consecutive failures/successes to determine route health status.
Triggers HEALTH_CHECK_FAILURE alerts when the failure threshold is reached
and sends recovery notifications after 2 consecutive successes from an
unhealthy state.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx

from app.schemas.notifications import AlertContext, ConditionType

logger = logging.getLogger(__name__)

# Probe configuration
PROBE_TIMEOUT_SECONDS = 10
USER_AGENT = "APISIX-Dashboard-HealthCheck/1.0"

# Recovery requires 2 consecutive successes
RECOVERY_THRESHOLD = 2


class ProbeStatus(str, Enum):
    """Health status of a probed route."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass
class ProbeResult:
    """Result of a single health check probe."""
    success: bool
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[float] = None


@dataclass
class ProbeState:
    """Tracks consecutive probe results for a route."""
    route_id: str
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_probe_time: Optional[datetime] = None
    last_status: Optional[ProbeStatus] = None
    last_error: Optional[str] = None


class HealthCheckProber:
    """Manages periodic HTTP health-check probes for configured routes.

    Maintains in-memory state tracking consecutive failures and successes
    per route. Triggers alerts when the configured failure threshold is
    reached and recovery notifications after 2 consecutive successes from
    an unhealthy state.
    """

    def __init__(self):
        self._probe_state: dict[str, ProbeState] = {}

    async def probe_route(self, route_id: str, url: str) -> ProbeResult:
        """Send an HTTP GET request to the route's health-check URL.

        Uses a 10-second timeout and a custom User-Agent header identifying
        the request as a health-check probe.

        Args:
            route_id: The route identifier.
            url: The health-check URL to probe.

        Returns:
            ProbeResult indicating success (2xx) or failure (non-2xx,
            connection error, DNS failure, timeout).
        """
        headers = {"User-Agent": USER_AGENT}

        try:
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
                response = await client.get(url, headers=headers)

            # Classify: 2xx = success, all else = failure
            if 200 <= response.status_code <= 299:
                return ProbeResult(
                    success=True,
                    status_code=response.status_code,
                )
            else:
                return ProbeResult(
                    success=False,
                    status_code=response.status_code,
                    error_message=f"Non-2xx response: {response.status_code}",
                )

        except httpx.TimeoutException as exc:
            logger.warning(
                "Health check timeout for route %s at %s: %s",
                route_id, url, exc,
            )
            return ProbeResult(
                success=False,
                error_message=f"Timeout after {PROBE_TIMEOUT_SECONDS}s",
            )

        except httpx.ConnectError as exc:
            error_str = str(exc)
            # Detect DNS failures from the error message
            if "name or service not known" in error_str.lower() or "dns" in error_str.lower():
                logger.warning(
                    "DNS resolution failure for route %s at %s: %s",
                    route_id, url, exc,
                )
                return ProbeResult(
                    success=False,
                    error_message=f"DNS resolution failure: {exc}",
                )
            logger.warning(
                "Connection error for route %s at %s: %s",
                route_id, url, exc,
            )
            return ProbeResult(
                success=False,
                error_message=f"Connection error: {exc}",
            )

        except httpx.HTTPError as exc:
            logger.warning(
                "HTTP error for route %s at %s: %s",
                route_id, url, exc,
            )
            return ProbeResult(
                success=False,
                error_message=f"HTTP error: {exc}",
            )

        except Exception as exc:
            logger.error(
                "Unexpected error probing route %s at %s: %s",
                route_id, url, exc,
            )
            return ProbeResult(
                success=False,
                error_message=f"Unexpected error: {exc}",
            )

    def update_state(
        self,
        route_id: str,
        result: ProbeResult,
        failure_threshold: int = 3,
        route_name: str = "",
        rule_id: int = 0,
        rule_name: str = "",
    ) -> Optional[AlertContext]:
        """Update probe state for a route and determine if an alert should fire.

        Tracks consecutive failures and successes. Returns an AlertContext
        when:
        - The consecutive failure count reaches the configured threshold
          (triggers a HEALTH_CHECK_FAILURE alert).
        - The route recovers with 2 consecutive successes from an unhealthy
          state (triggers a recovery notification).

        A success resets the consecutive failure counter to zero.
        A failure resets the consecutive success counter to zero.

        Args:
            route_id: The route identifier.
            result: The probe result from probe_route().
            failure_threshold: Number of consecutive failures to trigger alert.
            route_name: Human-readable route name for alert context.
            rule_id: The alert rule ID for context.
            rule_name: The alert rule name for context.

        Returns:
            AlertContext if an alert or recovery should be triggered, None otherwise.
        """
        # Get or create state for this route
        if route_id not in self._probe_state:
            self._probe_state[route_id] = ProbeState(route_id=route_id)

        state = self._probe_state[route_id]
        state.last_probe_time = datetime.now(timezone.utc)

        if result.success:
            # Success: reset failure counter, increment success counter
            state.consecutive_failures = 0
            state.consecutive_successes += 1
            state.last_error = None

            # Check for recovery: 2 consecutive successes from unhealthy state
            if (
                state.last_status == ProbeStatus.UNHEALTHY
                and state.consecutive_successes >= RECOVERY_THRESHOLD
            ):
                state.last_status = ProbeStatus.HEALTHY
                logger.info(
                    "Route %s recovered after %d consecutive successes",
                    route_id, state.consecutive_successes,
                )
                return AlertContext(
                    rule_id=rule_id,
                    rule_name=rule_name,
                    route_id=route_id,
                    route_name=route_name,
                    condition_type=ConditionType.HEALTH_CHECK_FAILURE,
                    metric_values={
                        "consecutive_successes": state.consecutive_successes,
                    },
                    threshold=failure_threshold,
                    evaluation_window_start=state.last_probe_time,
                    evaluation_window_end=state.last_probe_time,
                    is_recovery=True,
                )

            # If already healthy or not yet unhealthy, just update status
            if state.last_status is None:
                state.last_status = ProbeStatus.HEALTHY

        else:
            # Failure: reset success counter, increment failure counter
            state.consecutive_successes = 0
            state.consecutive_failures += 1
            state.last_error = result.error_message

            # Check if failure threshold reached
            if state.consecutive_failures >= failure_threshold:
                # Only trigger alert on the exact threshold crossing
                if state.consecutive_failures == failure_threshold:
                    state.last_status = ProbeStatus.UNHEALTHY
                    logger.warning(
                        "Route %s unhealthy: %d consecutive failures (threshold: %d)",
                        route_id, state.consecutive_failures, failure_threshold,
                    )
                    return AlertContext(
                        rule_id=rule_id,
                        rule_name=rule_name,
                        route_id=route_id,
                        route_name=route_name,
                        condition_type=ConditionType.HEALTH_CHECK_FAILURE,
                        metric_values={
                            "consecutive_failures": state.consecutive_failures,
                            "last_error": result.error_message or "Unknown",
                        },
                        threshold=failure_threshold,
                        evaluation_window_start=state.last_probe_time,
                        evaluation_window_end=state.last_probe_time,
                        is_recovery=False,
                    )

        return None

    def get_state(self, route_id: str) -> Optional[ProbeState]:
        """Get the current probe state for a route.

        Args:
            route_id: The route identifier.

        Returns:
            ProbeState if the route has been probed, None otherwise.
        """
        return self._probe_state.get(route_id)

    def reset_state(self, route_id: str) -> None:
        """Reset probe state for a route (e.g., when a rule is deleted).

        Args:
            route_id: The route identifier.
        """
        if route_id in self._probe_state:
            del self._probe_state[route_id]

    def reset_all(self) -> None:
        """Reset all probe states (e.g., on scheduler restart)."""
        self._probe_state.clear()
