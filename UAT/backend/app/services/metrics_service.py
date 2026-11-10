"""Prometheus metrics scraping and parsing service for APISIX."""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

# Default port APISIX exposes Prometheus metrics on (matches the apisix-metrics Service targetPort)
DEFAULT_METRICS_PORT = 9091


@dataclass
class PodMetrics:
    """Legacy pod metrics structure (kept for API compatibility)."""
    pod: str
    cpu_usage: float = 0.0
    memory_bytes: int = 0


@dataclass
class ApisixMetrics:
    """Parsed APISIX Prometheus metrics."""
    http_requests_total: float = 0.0
    connections: Dict[str, float] = field(default_factory=dict)
    bandwidth_bytes: Dict[str, float] = field(default_factory=dict)
    http_status: Dict[str, float] = field(default_factory=dict)
    http_latency: Dict[str, float] = field(default_factory=dict)
    etcd_reachable: float = 0.0
    shared_dict_capacity: Dict[str, float] = field(default_factory=dict)
    shared_dict_free: Dict[str, float] = field(default_factory=dict)


def fetch_metrics() -> str:
    """Fetch raw Prometheus metrics text from the configured endpoint."""
    try:
        with httpx.Client(timeout=settings.APISIX_METRICS_TIMEOUT) as client:
            response = client.get(settings.APISIX_METRICS_URL)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("Metrics endpoint unreachable: %s", e)
        raise HTTPException(status_code=503, detail="Metrics endpoint unreachable")

    if response.status_code >= 300:
        raise HTTPException(
            status_code=502,
            detail=f"Metrics endpoint returned {response.status_code}",
        )
    return response.text


def parse_prometheus(text: str) -> List[PodMetrics]:
    """Parse Prometheus text format and extract metrics.
    
    Returns PodMetrics list for API compatibility. For APISIX metrics,
    we create synthetic entries from the available data.
    """
    pods: dict[str, PodMetrics] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Try to extract pod label
        pod_match = re.search(r'pod="([^"]+)"', line)
        if pod_match:
            pod_name = pod_match.group(1)
            if pod_name not in pods:
                pods[pod_name] = PodMetrics(pod=pod_name)

            parts = line.split(" ")
            if len(parts) < 2:
                continue
            metric_part = parts[0]
            try:
                value = float(parts[1])
            except ValueError:
                continue

            if "container_cpu_usage_seconds_total" in metric_part:
                pods[pod_name].cpu_usage = value
            elif "container_memory_working_set_bytes" in metric_part:
                pods[pod_name].memory_bytes = int(value)

    # If no pod-level metrics found, parse APISIX native metrics
    if not pods:
        pods = _parse_apisix_native(text)

    return list(pods.values())


def parse_apisix_metrics(text: str) -> Dict[str, Any]:
    """Parse APISIX-native Prometheus metrics into a structured dict."""
    metrics: Dict[str, Any] = {
        "http_requests_total": 0,
        "connections": {},
        "bandwidth": {},
        "http_status": {},
        "latency": {},
        "etcd_reachable": 0,
        "shared_dict": [],
        "route_requests": {},
    }

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Split on the last space to handle labels with spaces (e.g. route names)
        # Format: metric_name{labels} value
        last_space = line.rfind(" ")
        if last_space <= 0:
            continue

        metric_part = line[:last_space]
        try:
            value = float(line[last_space + 1:])
        except ValueError:
            continue

        # Total HTTP requests
        if metric_part == "apisix_http_requests_total":
            metrics["http_requests_total"] = value

        # Connections by state
        elif "apisix_nginx_http_current_connections" in metric_part:
            state_match = re.search(r'state="([^"]+)"', metric_part)
            if state_match:
                metrics["connections"][state_match.group(1)] = value

        # Bandwidth by type and route
        elif "apisix_bandwidth" in metric_part:
            type_match = re.search(r'type="([^"]+)"', metric_part)
            route_match = re.search(r'route="([^"]+)"', metric_part)
            if type_match:
                key = type_match.group(1)
                if route_match:
                    key = f"{route_match.group(1)}_{key}"
                metrics["bandwidth"][key] = metrics["bandwidth"].get(key, 0) + value

        # HTTP status codes
        elif "apisix_http_status" in metric_part:
            code_match = re.search(r'code="([^"]+)"', metric_part)
            route_match = re.search(r'route="([^"]+)"', metric_part)
            if code_match:
                code = code_match.group(1)
                metrics["http_status"][code] = metrics["http_status"].get(code, 0) + value

            # Per-route request counts
            if route_match:
                route_name = route_match.group(1)
                if route_name not in metrics["route_requests"]:
                    metrics["route_requests"][route_name] = {"total": 0, "by_status": {}}
                metrics["route_requests"][route_name]["total"] += value
                if code_match:
                    code = code_match.group(1)
                    metrics["route_requests"][route_name]["by_status"][code] = (
                        metrics["route_requests"][route_name]["by_status"].get(code, 0) + value
                    )

        # HTTP latency
        elif "apisix_http_latency" in metric_part:
            type_match = re.search(r'type="([^"]+)"', metric_part)
            if type_match:
                lt = type_match.group(1)
                metrics["latency"][lt] = metrics["latency"].get(lt, 0) + value

        # etcd reachable
        elif metric_part == "apisix_etcd_reachable":
            metrics["etcd_reachable"] = value

        # Shared dict
        elif "apisix_shared_dict_capacity_bytes" in metric_part:
            name_match = re.search(r'name="([^"]+)"', metric_part)
            if name_match:
                metrics["shared_dict"].append({
                    "name": name_match.group(1),
                    "capacity_bytes": value,
                })

    return metrics


def _percentile_from_buckets(buckets: List[Tuple[float, float]], quantile: float) -> float:
    """Estimate a quantile from cumulative Prometheus histogram buckets.

    `buckets` is a list of (le_upper_bound, cumulative_count) sorted ascending by
    upper bound (the final bound may be +Inf, represented as float('inf')).
    Uses linear interpolation within the matching bucket for a better estimate than
    the raw bucket boundary. Returns the estimated value (milliseconds for APISIX
    latency). Returns 0.0 when there is no data.
    """
    if not buckets:
        return 0.0
    total = buckets[-1][1]
    if total <= 0:
        return 0.0

    target = quantile * total
    prev_bound = 0.0
    prev_count = 0.0
    for upper, cum in buckets:
        if cum >= target:
            # Interpolate within [prev_bound, upper] based on where target falls.
            if upper == float("inf"):
                # Open-ended top bucket: fall back to the last finite bound.
                return prev_bound if prev_bound > 0 else 0.0
            bucket_count = cum - prev_count
            if bucket_count <= 0:
                return upper
            frac = (target - prev_count) / bucket_count
            return prev_bound + frac * (upper - prev_bound)
        prev_bound = upper if upper != float("inf") else prev_bound
        prev_count = cum
    return prev_bound


def parse_route_latency(text: str) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Parse per-route latency histograms into percentile estimates.

    Returns: { route_name: { latency_type: {p50, p95, p99, count} } }
    where latency_type is one of 'request' (total), 'upstream', 'apisix'.
    """
    # route -> type -> le -> cumulative count   (summed across node/consumer labels)
    raw: Dict[str, Dict[str, Dict[float, float]]] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("apisix_http_latency_bucket"):
            continue
        last_space = line.rfind(" ")
        if last_space <= 0:
            continue
        label_part = line[:last_space]
        try:
            value = float(line[last_space + 1:])
        except ValueError:
            continue

        route_match = re.search(r'route="([^"]*)"', label_part)
        type_match = re.search(r'type="([^"]*)"', label_part)
        le_match = re.search(r'le="([^"]*)"', label_part)
        if not (route_match and type_match and le_match):
            continue

        route = route_match.group(1)
        ltype = type_match.group(1)
        le_str = le_match.group(1)
        le = float("inf") if le_str in ("+Inf", "Inf") else float(le_str)

        raw.setdefault(route, {}).setdefault(ltype, {})
        # Sum cumulative counts for the same le across node/consumer label combos.
        raw[route][ltype][le] = raw[route][ltype].get(le, 0.0) + value

    result: Dict[str, Dict[str, Dict[str, float]]] = {}
    for route, types in raw.items():
        result[route] = {}
        for ltype, le_map in types.items():
            buckets = sorted(le_map.items(), key=lambda kv: kv[0])
            total = buckets[-1][1] if buckets else 0.0
            result[route][ltype] = {
                "p50": round(_percentile_from_buckets(buckets, 0.50), 1),
                "p95": round(_percentile_from_buckets(buckets, 0.95), 1),
                "p99": round(_percentile_from_buckets(buckets, 0.99), 1),
                "count": int(total),
            }
    return result


def parse_route_nodes(text: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Parse per-route, per-upstream-node traffic and status breakdown.

    Uses the `node` label present on apisix_http_status (status codes per backend
    node) and apisix_bandwidth (bytes per backend node). This gives an "upstream
    node" view without active health checks being configured.

    Returns: { route_name: { node_ip: {by_status, total, bandwidth_ingress,
               bandwidth_egress} } }
    """
    routes: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _node_entry(route: str, node: str) -> Dict[str, Any]:
        return routes.setdefault(route, {}).setdefault(
            node,
            {"by_status": {}, "total": 0, "bandwidth_ingress": 0, "bandwidth_egress": 0},
        )

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        last_space = line.rfind(" ")
        if last_space <= 0:
            continue
        label_part = line[:last_space]
        try:
            value = float(line[last_space + 1:])
        except ValueError:
            continue

        if label_part.startswith("apisix_http_status"):
            route_match = re.search(r'route="([^"]*)"', label_part)
            node_match = re.search(r'node="([^"]*)"', label_part)
            code_match = re.search(r'code="([^"]*)"', label_part)
            if not (route_match and node_match and code_match):
                continue
            node = node_match.group(1)
            if not node:
                continue
            entry = _node_entry(route_match.group(1), node)
            code = code_match.group(1)
            entry["by_status"][code] = entry["by_status"].get(code, 0) + int(value)
            entry["total"] += int(value)

        elif label_part.startswith("apisix_bandwidth"):
            route_match = re.search(r'route="([^"]*)"', label_part)
            node_match = re.search(r'node="([^"]*)"', label_part)
            type_match = re.search(r'type="([^"]*)"', label_part)
            if not (route_match and node_match and type_match):
                continue
            node = node_match.group(1)
            if not node:
                continue
            entry = _node_entry(route_match.group(1), node)
            if type_match.group(1) == "ingress":
                entry["bandwidth_ingress"] += int(value)
            elif type_match.group(1) == "egress":
                entry["bandwidth_egress"] += int(value)

    return routes


def _metrics_path_and_port() -> Tuple[str, int]:
    """Derive the metrics path and port from the configured APISIX_METRICS_URL.

    The configured URL points at the apisix-metrics Service (which load-balances
    across pods). For per-pod scraping we reuse the same path and port but swap
    the host for each individual pod IP.
    """
    parsed = urlparse(settings.APISIX_METRICS_URL)
    port = parsed.port or DEFAULT_METRICS_PORT
    path = parsed.path or "/apisix/prometheus/metrics"
    return path, port


def _is_apisix_pod(pod: Dict[str, Any]) -> bool:
    """Return True if a pod looks like an APISIX gateway pod exposing metrics."""
    labels = pod.get("labels", {}) or {}
    # APISIX StatefulSet pods carry app=apisix (per cluster config). Fall back to name match.
    if labels.get("app") == "apisix":
        return True
    name = (pod.get("name") or "").lower()
    return name.startswith("apisix") and "dashboard" not in name


def fetch_metrics_per_pod() -> Dict[str, str]:
    """Scrape the Prometheus metrics endpoint on each APISIX pod individually.

    Returns a mapping of pod_name -> raw Prometheus text. Scraping each pod by IP
    avoids the apisix-metrics Service load-balancing that otherwise returns only a
    single (arbitrary) pod's counters per request.
    """
    # Imported here to avoid a circular import at module load time.
    from app.services.k8s_service import get_pods

    path, port = _metrics_path_and_port()
    results: Dict[str, str] = {}

    try:
        pods = get_pods()
    except HTTPException as e:
        logger.error("Could not list pods for per-pod metrics: %s", e.detail)
        raise

    apisix_pods = [
        p for p in pods
        if _is_apisix_pod(p) and p.get("ip") and p.get("phase") == "Running"
    ]

    if not apisix_pods:
        logger.warning("No running APISIX pods with an IP found for per-pod metrics")
        return results

    with httpx.Client(timeout=settings.APISIX_METRICS_TIMEOUT, verify=False) as client:
        for pod in apisix_pods:
            pod_name = pod["name"]
            url = urlunparse(("http", f"{pod['ip']}:{port}", path, "", "", ""))
            try:
                resp = client.get(url)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("Metrics scrape failed for pod %s (%s): %s", pod_name, url, e)
                continue
            if resp.status_code >= 300:
                logger.warning(
                    "Metrics scrape for pod %s returned %d", pod_name, resp.status_code
                )
                continue
            results[pod_name] = resp.text

    return results


def parse_route_requests_per_pod() -> List[Dict[str, Any]]:
    """Return per-route request counts broken down by APISIX pod.

    Each entry: {route_id, per_pod: {pod_name: {total, by_status}}}
    """
    per_pod_raw = fetch_metrics_per_pod()

    # route_id -> pod_name -> {total, by_status}
    routes: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for pod_name, raw in per_pod_raw.items():
        parsed = parse_apisix_metrics(raw)
        for route_id, data in parsed.get("route_requests", {}).items():
            routes.setdefault(route_id, {})[pod_name] = {
                "total": int(data.get("total", 0)),
                "by_status": {k: int(v) for k, v in data.get("by_status", {}).items()},
            }

    result = []
    for route_id, per_pod in routes.items():
        result.append({"route_id": route_id, "per_pod": per_pod})
    return result


def _parse_apisix_native(text: str) -> dict:
    """Create synthetic PodMetrics from APISIX native metrics for chart display."""
    apisix_data = parse_apisix_metrics(text)

    pods = {}
    # Create entries from connection states for visualization
    for state, value in apisix_data.get("connections", {}).items():
        pod_name = f"connections_{state}"
        pods[pod_name] = PodMetrics(
            pod=pod_name,
            cpu_usage=value,  # Using cpu_usage field for connection count
            memory_bytes=0,
        )

    # Add total requests as a synthetic entry
    if apisix_data.get("http_requests_total"):
        pods["http_requests"] = PodMetrics(
            pod="http_requests",
            cpu_usage=apisix_data["http_requests_total"],
            memory_bytes=0,
        )

    return pods
