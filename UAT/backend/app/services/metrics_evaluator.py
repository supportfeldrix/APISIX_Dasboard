"""Metrics evaluator — evaluates Prometheus metrics against alert rule thresholds.

Queries the APISIX Prometheus metrics endpoint and compares per-route HTTP
status code counts against configured alert rule thresholds to determine
whether notifications should be triggered.
"""
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

import httpx

from app.config import settings
from app.schemas.notifications import AlertContext, ConditionType

logger = logging.getLogger(__name__)

# Minimum total responses required before evaluating error rate
MIN_RESPONSES_FOR_RATE = 10


def fetch_route_metrics() -> Dict[str, Dict[str, float]]:
    """Fetch and parse per-route HTTP status code metrics from Prometheus.

    Returns a dict keyed by route_id, where each value is a dict mapping
    HTTP status code strings (e.g. "401", "502") to their request counts.

    Example return:
        {
            "route_1": {"200": 100, "401": 5, "403": 2, "502": 1},
            "route_2": {"200": 50, "500": 3},
        }
    """
    try:
        with httpx.Client(timeout=settings.APISIX_METRICS_TIMEOUT) as client:
            response = client.get(settings.APISIX_METRICS_URL)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("Metrics endpoint unreachable: %s", e)
        raise MetricsUnavailableError(f"Metrics endpoint unreachable: {e}") from e

    if response.status_code >= 300:
        logger.warning("Metrics endpoint returned status %d", response.status_code)
        raise MetricsUnavailableError(
            f"Metrics endpoint returned {response.status_code}"
        )

    return parse_route_status_metrics(response.text)


def parse_route_status_metrics(text: str) -> Dict[str, Dict[str, float]]:
    """Parse raw Prometheus text and extract per-route HTTP status counts.

    Looks for lines matching the apisix_http_status metric with route and code labels.
    Format: apisix_http_status{code="NNN",route="ROUTE_NAME",...} VALUE

    Note: Route names may contain spaces (e.g. "RTS - OAuth2 - Secure"), so we
    cannot split on space to separate the metric labels from the value. Instead
    we split from the right (rsplit) on the closing brace + space pattern.

    Args:
        text: Raw Prometheus metrics text.

    Returns:
        Dict mapping route_id -> {status_code -> count}.
    """
    route_metrics: Dict[str, Dict[str, float]] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if "apisix_http_status" not in line:
            continue

        # Split on "} " to separate metric labels from value.
        # Format: metric_name{labels...} value
        brace_idx = line.rfind("}")
        if brace_idx < 0:
            continue

        metric_part = line[: brace_idx + 1]
        value_part = line[brace_idx + 1 :].strip()

        try:
            value = float(value_part)
        except ValueError:
            continue

        # Extract route and code labels from the full metric part
        route_match = re.search(r'route="([^"]+)"', metric_part)
        code_match = re.search(r'code="([^"]+)"', metric_part)

        if not route_match or not code_match:
            continue

        route_id = route_match.group(1)
        code = code_match.group(1)

        if route_id not in route_metrics:
            route_metrics[route_id] = {}

        route_metrics[route_id][code] = (
            route_metrics[route_id].get(code, 0) + value
        )

    return route_metrics


def evaluate_jwt_failure(
    route_metrics: Dict[str, Dict[str, float]],
    route_id: str,
    threshold: int,
) -> Optional[AlertContext]:
    """Evaluate JWT failure condition for a route.

    Sums 401 and 403 response counts and compares against the threshold.
    Returns an AlertContext if the threshold is met or exceeded, None otherwise.

    Args:
        route_metrics: Per-route status code counts from parse_route_status_metrics.
        route_id: The route to evaluate.
        threshold: The count threshold that triggers an alert.

    Returns:
        AlertContext if threshold breached, None otherwise.
    """
    metrics = route_metrics.get(route_id)
    if metrics is None:
        logger.debug("No metrics data for route %s, skipping JWT failure evaluation", route_id)
        return None

    # Check total requests > 0 (route must have some traffic)
    total = sum(metrics.values())
    if total == 0:
        return None

    count_401 = metrics.get("401", 0)
    count_403 = metrics.get("403", 0)
    jwt_failure_count = count_401 + count_403

    if jwt_failure_count >= threshold:
        now = datetime.now(timezone.utc)
        return AlertContext(
            rule_id=0,  # Caller sets this
            rule_name="",  # Caller sets this
            route_id=route_id,
            route_name="",  # Caller sets this
            condition_type=ConditionType.JWT_FAILURE,
            metric_values={
                "401_count": count_401,
                "403_count": count_403,
                "total_jwt_failures": jwt_failure_count,
            },
            threshold=threshold,
            evaluation_window_start=now - timedelta(minutes=5),
            evaluation_window_end=now,
        )

    return None


def evaluate_upstream_error(
    route_metrics: Dict[str, Dict[str, float]],
    route_id: str,
    threshold: int,
) -> Optional[AlertContext]:
    """Evaluate upstream error condition for a route.

    Sums all 5xx (500–599) response counts and compares against the threshold.
    Returns an AlertContext if the threshold is met or exceeded, None otherwise.

    Args:
        route_metrics: Per-route status code counts from parse_route_status_metrics.
        route_id: The route to evaluate.
        threshold: The count threshold that triggers an alert.

    Returns:
        AlertContext if threshold breached, None otherwise.
    """
    metrics = route_metrics.get(route_id)
    if metrics is None:
        logger.debug("No metrics data for route %s, skipping upstream error evaluation", route_id)
        return None

    # Check total requests > 0 (skip if no traffic)
    total = sum(metrics.values())
    if total == 0:
        return None

    # Sum all 5xx status codes (500–599) and build breakdown dict
    upstream_error_count = 0.0
    fivexx_breakdown = {}
    for code, count in metrics.items():
        try:
            code_int = int(code)
        except (ValueError, TypeError):
            continue
        if 500 <= code_int <= 599:
            upstream_error_count += count
            fivexx_breakdown[code] = count

    if upstream_error_count >= threshold:
        now = datetime.now(timezone.utc)
        return AlertContext(
            rule_id=0,  # Caller sets this
            rule_name="",  # Caller sets this
            route_id=route_id,
            route_name="",  # Caller sets this
            condition_type=ConditionType.UPSTREAM_ERROR,
            metric_values={
                "5xx_breakdown": fivexx_breakdown,
                "total_upstream_errors": upstream_error_count,
            },
            threshold=threshold,
            evaluation_window_start=now - timedelta(minutes=5),
            evaluation_window_end=now,
        )

    return None


def evaluate_client_error(
    route_metrics: Dict[str, Dict[str, float]],
    route_id: str,
    threshold: int,
) -> Optional[AlertContext]:
    """Evaluate client error condition for a route.

    Sums all 4xx (400–499) response counts and compares against the threshold.
    Returns an AlertContext if the threshold is met or exceeded, None otherwise.

    Note: This function provides the cumulative evaluation. The background
    scheduler uses delta-based logic (same pattern as UPSTREAM_ERROR) to only
    alert on NEW 4xx errors since the last evaluation cycle.

    Args:
        route_metrics: Per-route status code counts from parse_route_status_metrics.
        route_id: The route to evaluate.
        threshold: The count threshold that triggers an alert.

    Returns:
        AlertContext if threshold breached, None otherwise.
    """
    metrics = route_metrics.get(route_id)
    if metrics is None:
        logger.debug("No metrics data for route %s, skipping client error evaluation", route_id)
        return None

    # Check total requests > 0 (skip if no traffic)
    total = sum(metrics.values())
    if total == 0:
        return None

    # Sum all 4xx status codes (400–499) and build breakdown dict
    client_error_count = 0.0
    fourxx_breakdown = {}
    for code, count in metrics.items():
        try:
            code_int = int(code)
        except (ValueError, TypeError):
            continue
        if 400 <= code_int <= 499:
            client_error_count += count
            fourxx_breakdown[code] = count

    if client_error_count >= threshold:
        now = datetime.now(timezone.utc)
        return AlertContext(
            rule_id=0,  # Caller sets this
            rule_name="",  # Caller sets this
            route_id=route_id,
            route_name="",  # Caller sets this
            condition_type=ConditionType.CLIENT_ERROR,
            metric_values={
                "4xx_breakdown": fourxx_breakdown,
                "total_client_errors": client_error_count,
            },
            threshold=threshold,
            evaluation_window_start=now - timedelta(minutes=5),
            evaluation_window_end=now,
        )

    return None


def calculate_error_rate(
    route_metrics: Dict[str, Dict[str, float]],
    route_id: str,
) -> Optional[float]:
    """Calculate the error rate for a route as a percentage.

    Error rate = (4xx + 5xx responses) / total responses * 100, rounded to 2 decimals.

    Returns None if:
    - No metrics exist for the route
    - Total responses is zero
    - Total responses is less than MIN_RESPONSES_FOR_RATE (10)

    Args:
        route_metrics: Per-route status code counts from parse_route_status_metrics.
        route_id: The route to evaluate.

    Returns:
        Error rate percentage rounded to 2 decimal places, or None if insufficient data.
    """
    metrics = route_metrics.get(route_id)
    if metrics is None:
        return None

    total = sum(metrics.values())
    if total == 0:
        return None

    if total < MIN_RESPONSES_FOR_RATE:
        return None

    error_count = 0.0
    for code, count in metrics.items():
        try:
            code_int = int(code)
        except (ValueError, TypeError):
            continue
        if 400 <= code_int <= 599:
            error_count += count

    error_rate = (error_count / total) * 100
    return round(error_rate, 2)


def evaluate_high_error_rate(
    route_metrics: Dict[str, Dict[str, float]],
    route_id: str,
    threshold: int,
) -> Optional[AlertContext]:
    """Evaluate high error rate condition for a route.

    Calculates the error rate and compares against the threshold percentage.
    The alert triggers when the error rate is strictly greater than the threshold.
    Requires at least MIN_RESPONSES_FOR_RATE (10) total responses.

    Args:
        route_metrics: Per-route status code counts from parse_route_status_metrics.
        route_id: The route to evaluate.
        threshold: The percentage threshold (1-100) that triggers an alert.

    Returns:
        AlertContext if error rate exceeds threshold, None otherwise.
    """
    error_rate = calculate_error_rate(route_metrics, route_id)
    if error_rate is None:
        return None

    if error_rate > threshold:
        metrics = route_metrics[route_id]
        total = sum(metrics.values())

        # Calculate breakdown
        error_count = 0.0
        count_4xx = 0.0
        count_5xx = 0.0
        for code, count in metrics.items():
            try:
                code_int = int(code)
            except (ValueError, TypeError):
                continue
            if 400 <= code_int <= 499:
                count_4xx += count
            elif 500 <= code_int <= 599:
                count_5xx += count

        now = datetime.now(timezone.utc)
        return AlertContext(
            rule_id=0,  # Caller sets this
            rule_name="",  # Caller sets this
            route_id=route_id,
            route_name="",  # Caller sets this
            condition_type=ConditionType.HIGH_ERROR_RATE,
            metric_values={
                "error_rate": error_rate,
                "4xx_count": count_4xx,
                "5xx_count": count_5xx,
                "total_requests": total,
            },
            threshold=threshold,
            evaluation_window_start=now - timedelta(minutes=5),
            evaluation_window_end=now,
        )

    return None


class MetricsUnavailableError(Exception):
    """Raised when the Prometheus metrics endpoint cannot be reached or returns an error."""
    pass
