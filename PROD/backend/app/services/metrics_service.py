"""Prometheus metrics scraping and parsing service for APISIX."""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)


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
