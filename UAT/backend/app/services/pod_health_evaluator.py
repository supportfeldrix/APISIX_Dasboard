"""Pod health evaluator — monitors pod status for OOMKilled, CrashLoopBackOff, restarts, and pod recreation.

Queries the Kubernetes API for pod status and detects unhealthy conditions:
- Pod not running (phase != Running)
- OOMKilled containers
- CrashLoopBackOff state
- Excessive restarts (above configured threshold)
- Pod recreation (StatefulSet rolling update, eviction, or rescheduling)
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from app.schemas.notifications import AlertContext, ConditionType
from app.services.k8s_service import get_pods

logger = logging.getLogger(__name__)


def evaluate_pod_health(
    route_id: str,
    threshold: int,
    previous_pod_starts: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[AlertContext], Dict[str, str]]:
    """Evaluate pod health for the namespace.

    The route_id field is used as a pod name pattern filter.
    If route_id is "*" or empty, all pods are monitored.
    Otherwise, only pods whose name contains route_id are checked.

    The threshold represents the maximum allowed restarts before alerting.

    Triggers an alert when:
    - A pod is in CrashLoopBackOff state
    - A pod has been OOMKilled
    - A pod's restart count exceeds the threshold
    - A pod is not in Running phase (Failed, Unknown, etc.)
    - A pod has been recreated (startTime changed since last evaluation)

    Pod recreation detection:
    - On each evaluation, the current startTime of each matched pod is compared
      against the previously recorded startTime (passed via previous_pod_starts).
    - If the startTime differs (or the pod name was previously tracked with a
      different startTime), the pod was deleted and recreated — e.g. during a
      StatefulSet rolling update, eviction, or manual deletion.
    - On the FIRST evaluation (previous_pod_starts is empty/None), current start
      times are recorded as baseline and no alert is fired.

    Args:
        route_id: Pod name pattern to filter (or "*" for all pods).
        threshold: Maximum restart count before alerting.
        previous_pod_starts: Dict mapping pod name -> last-seen startTime ISO string.
                             Pass None or {} on first cycle (baseline capture).

    Returns:
        Tuple of (AlertContext or None, current_pod_starts dict).
        The caller MUST store the returned current_pod_starts for the next cycle.
    """
    try:
        pods = get_pods()
    except Exception as exc:
        logger.error("Failed to fetch pods for health evaluation: %s", exc)
        return None, previous_pod_starts or {}

    if not pods:
        return None, previous_pod_starts or {}

    # Filter pods by pattern
    pattern = route_id.strip() if route_id else "*"
    if pattern and pattern != "*":
        pods = [p for p in pods if pattern.lower() in p["name"].lower()]

    if previous_pod_starts is None:
        previous_pod_starts = {}

    # Build current start times for matched pods
    current_pod_starts: Dict[str, str] = {}
    unhealthy_pods = []

    for pod in pods:
        pod_name = pod.get("name", "")
        phase = pod.get("phase", "Unknown")
        start_time = pod.get("start_time", "")
        container_statuses = pod.get("container_statuses", [])

        # Track the current start time for this pod
        if pod_name and start_time:
            current_pod_starts[pod_name] = start_time

        # --- Pod recreation detection ---
        # Only fire if we have a previous baseline (not first cycle)
        if previous_pod_starts and pod_name and start_time:
            prev_start = previous_pod_starts.get(pod_name)
            if prev_start and prev_start != start_time:
                # Pod was recreated — startTime changed
                logger.info(
                    "Pod recreation detected: %s (previous start: %s, current start: %s)",
                    pod_name, prev_start, start_time,
                )
                unhealthy_pods.append({
                    "pod": pod_name,
                    "reason": f"Pod recreated (was started {prev_start}, now {start_time})",
                    "restarts": 0,
                })
                continue

        # Check for non-running pods (skip Succeeded build pods)
        if phase not in ("Running", "Succeeded", "Pending"):
            unhealthy_pods.append({
                "pod": pod_name,
                "reason": f"Pod phase: {phase}",
                "restarts": 0,
            })
            continue

        # Skip non-running pods for container checks
        if phase != "Running":
            continue

        # Check container statuses
        for cs in container_statuses:
            restarts = cs.get("restarts", 0)
            state = cs.get("state", "unknown")
            ready = cs.get("ready", False)

            # CrashLoopBackOff detection — pod is waiting and not ready
            if state == "waiting" and not ready:
                unhealthy_pods.append({
                    "pod": pod_name,
                    "reason": "CrashLoopBackOff or waiting state",
                    "restarts": restarts,
                })
                break

            # Pod not ready (starting up after a crash)
            if not ready and restarts >= threshold:
                unhealthy_pods.append({
                    "pod": pod_name,
                    "reason": f"Not ready after restart ({restarts} restarts)",
                    "restarts": restarts,
                })
                break

            # Excessive restarts — pod is ready but has restarted
            # Alert fires once, cooldown prevents spam
            if restarts >= threshold:
                unhealthy_pods.append({
                    "pod": pod_name,
                    "reason": f"Restart count ({restarts}) >= threshold ({threshold}) - now running",
                    "restarts": restarts,
                })
                break

    if not unhealthy_pods:
        return None, current_pod_starts

    # Build alert context with the first unhealthy pod (most critical)
    worst = unhealthy_pods[0]
    now = datetime.now(timezone.utc)

    return AlertContext(
        rule_id=0,  # Caller sets this
        rule_name="",  # Caller sets this
        route_id=route_id,
        route_name=worst["pod"],
        condition_type=ConditionType.POD_HEALTH,
        metric_values={
            "unhealthy_pod": worst["pod"],
            "reason": worst["reason"],
            "restart_count": worst["restarts"],
            "total_unhealthy": len(unhealthy_pods),
            "unhealthy_pods": [p["pod"] for p in unhealthy_pods[:5]],  # Top 5
        },
        threshold=threshold,
        evaluation_window_start=now,
        evaluation_window_end=now,
    ), current_pod_starts
