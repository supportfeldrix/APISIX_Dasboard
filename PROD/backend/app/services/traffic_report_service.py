"""Traffic report service — parses APISIX access logs for per-minute request counts.

Uses the Kubernetes exec API via WebSocket to read JSON-formatted access logs
from APISIX pods. Filters by route and date/time range, groups requests per
minute for business/audit reporting.
"""
import asyncio
import json
import logging
import os
import ssl
import struct
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

# South Africa Standard Time (UTC+2)
SAST = timezone(timedelta(hours=2))

import websockets

from app.config import settings

logger = logging.getLogger(__name__)

# APISIX pod names (StatefulSet) — UPDATE FOR YOUR ENVIRONMENT
APISIX_PODS = ["apisix-0", "apisix-1"]

# Log file mapping by route pattern
# PROD uses numeric route IDs — grep matches partial strings in the log
LOG_FILES = {
    "593676047602418605": "rcm-route.log",       # RCM - OAuth2
    "593671182427882413": "rcm-route.log",       # RCM - Passthrough
    "593672561984799661": "realtime-screening.log",  # RTS - OAuth2
    "593671458748629933": "realtime-screening.log",  # RTS - Passthrough
    "593671527551992749": "orchestrator-callback.log",  # OrchestratorCallback
    "593672000501711789": "keycloak-access.log",  # Keycloak External
    "593672493047219117": "keycloak-access.log",  # Keycloak Internal
    "602960270167376788": "keycloak-access.log",  # Keycloak Token Introspection
    "612956089574491028": "keycloak-access.log",  # Vendor Token Introspection
    "oidc-token-proxy": "keycloak-access.log",    # OIDC Token Proxy
    "access-log-all": "access.log",               # All traffic (access.log)
    "error-log-all": "error.log",                 # Errors only (error.log)
}

# Friendly names for the UI dropdown
ROUTE_NAMES = {
    "593676047602418605": "RCM - OAuth2",
    "593671182427882413": "RCM - Passthrough",
    "593672561984799661": "RTS - OAuth2",
    "593671458748629933": "RTS - Passthrough",
    "593671527551992749": "OrchestratorCallback",
    "593672000501711789": "Keycloak External",
    "593672493047219117": "Keycloak Internal",
    "602960270167376788": "Keycloak Token Introspection",
    "612956089574491028": "Vendor Token Introspection - Actimize",
    "oidc-token-proxy": "OIDC Token Proxy",
    "access-log-all": "All Traffic (access.log)",
    "error-log-all": "Errors (error.log)",
}

LOG_BASE_PATH = "/usr/local/apisix/logs"

# SA token path
SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def _get_log_file_for_route(route_id: str) -> str:
    """Determine which log file to read based on route ID."""
    for pattern, log_file in LOG_FILES.items():
        if pattern.lower() in route_id.lower():
            return log_file
    return "access.log"


async def _exec_in_pod_ws(pod_name: str, command: List[str]) -> str:
    """Execute a command in an APISIX pod using the K8s exec WebSocket API.

    Uses the in-cluster service account token for authentication.
    Returns stdout as a string.
    """
    namespace = settings.OC_NAMESPACE

    # Read SA token
    if not os.path.exists(SA_TOKEN_PATH):
        logger.error("SA token not found at %s", SA_TOKEN_PATH)
        return ""

    with open(SA_TOKEN_PATH, "r") as f:
        token = f.read().strip()

    # Build exec URL
    api_server = "kubernetes.default.svc"
    cmd_params = "&".join(f"command={urllib.parse.quote(c)}" for c in command)
    url = (
        f"wss://{api_server}/api/v1/namespaces/{namespace}/pods/{pod_name}"
        f"/exec?{cmd_params}&container=apisix&stdout=true&stderr=true&stdin=false&tty=false"
    )

    # SSL context with CA cert
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if os.path.exists(SA_CA_PATH):
        ssl_context.load_verify_locations(SA_CA_PATH)
    else:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    headers = {
        "Authorization": f"Bearer {token}",
    }

    stdout_data = []

    max_bytes = 10 * 1024 * 1024  # 10MB cap to prevent OOM
    total_bytes = 0

    try:
        async with websockets.connect(
            url,
            additional_headers=headers,
            ssl=ssl_context,
            subprotocols=["v4.channel.k8s.io"],
            open_timeout=15,
            close_timeout=30,
            ping_timeout=30,
            max_size=10 * 1024 * 1024,
        ) as ws:
            async for message in ws:
                if isinstance(message, bytes) and len(message) > 1:
                    # First byte is the channel number:
                    # 0 = stdin, 1 = stdout, 2 = stderr, 3 = error
                    channel = message[0]
                    data = message[1:].decode("utf-8", errors="replace")
                    if channel == 1:  # stdout
                        stdout_data.append(data)
                        total_bytes += len(message)
                        if total_bytes >= max_bytes:
                            logger.warning("Max bytes (%d) reached for pod %s, breaking", max_bytes, pod_name)
                            break
                    elif channel == 3:  # error/status
                        # Check if it's a success status
                        try:
                            status = json.loads(data)
                            if status.get("status") == "Success":
                                break
                        except json.JSONDecodeError:
                            pass

    except asyncio.TimeoutError:
        logger.warning("Timeout exec'ing into pod %s", pod_name)
    except Exception as exc:
        logger.error("WebSocket exec failed for pod %s: %s", pod_name, exc)

    return "".join(stdout_data)


def _exec_in_pod(pod_name: str, command: List[str]) -> str:
    """Synchronous wrapper for async WebSocket exec."""
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_exec_in_pod_ws(pod_name, command))
        loop.close()
        return result
    except Exception as exc:
        logger.error("Error in exec wrapper for pod %s: %s", pod_name, exc)
        return ""


def get_traffic_report(
    route_id: str,
    date: str,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
) -> Dict:
    """Generate a per-minute traffic report for a route on a given date.

    Reads JSON access logs from both APISIX pods, filters by route and
    date/time range, and groups requests per minute.

    Args:
        route_id: The route ID to filter (e.g. "realtimewsprovider-vendor-jwt").
        date: Date string in YYYY-MM-DD format.
        time_from: Optional start time HH:MM (default "00:00").
        time_to: Optional end time HH:MM (default "23:59").

    Returns:
        Dict with per-minute breakdown and summary.
    """
    if not time_from:
        time_from = "00:00"
    if not time_to:
        time_to = "23:59"

    log_file = _get_log_file_for_route(route_id)
    log_path = f"{LOG_BASE_PATH}/{log_file}"

    # Parse target date
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": f"Invalid date format: {date}. Use YYYY-MM-DD."}

    # Determine tail depth based on how far back the query date is.
    # Today: 20,000 lines is usually sufficient.
    # Yesterday/older: use tac (reverse file read) to find historical data quickly.
    now_sast = datetime.now(SAST)
    today = now_sast.date()
    days_ago = (today - target_date).days

    # Build grep command to filter by route_id
    # For access-log-all and error-log-all, read all lines (no route filter)
    if route_id in ("access-log-all", "error-log-all"):
        # For access/error logs, use grep with date string
        # access.log format: IP - - [15/May/2026:12:28:13 +0200] ...
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            log_date_str = date_obj.strftime("%d/%b/%Y")  # e.g. "15/May/2026"
        except ValueError:
            log_date_str = date
        if days_ago <= 0:
            # Today: tail for speed, then grep by date
            grep_cmd = ["sh", "-c", f"tail -20000 {log_path} | grep -a '{log_date_str}' | tail -500"]
        else:
            # Historical: use tac to read from end of file (recent first),
            # grep by date, limited to 500 lines
            grep_cmd = ["sh", "-c", f"tac {log_path} | grep -a '{log_date_str}' | head -500"]
    else:
        # For JSON route logs:
        # - Today: tail recent lines then filter by route (fast, small transfer)
        # - Historical: use tac (reverse read) to read from end of file backwards,
        #   then grep for route_id. Since yesterday's data is just before today's
        #   in the file, this finds it quickly without scanning from the beginning.
        #   Limited to 10,000 matching lines to prevent timeouts.
        if days_ago <= 0:
            grep_cmd = ["sh", "-c", f"tail -20000 {log_path} | grep -a '{route_id}' | tail -500"]
        else:
            grep_cmd = ["sh", "-c", f"tac {log_path} | grep -a '{route_id}' | head -500"]

    per_minute = defaultdict(lambda: {"count": 0, "total_latency": 0.0, "statuses": defaultdict(int)})
    total_requests = 0
    total_latency = 0.0

    for pod_name in APISIX_PODS:
        try:
            raw_output = _exec_in_pod(pod_name, grep_cmd)
            if not raw_output:
                logger.debug("No output from pod %s for route %s", pod_name, route_id)
                continue

            for line in raw_output.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Try JSON format first (route-specific logs)
                try:
                    entry = json.loads(line)
                    # Extract timestamp from start_time (epoch ms)
                    start_time_ms = entry.get("start_time")
                    if not start_time_ms:
                        continue
                    # Convert to SAST (UTC+2) for South Africa
                    ts = datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc)
                    ts_local = ts.astimezone(SAST)
                    latency = entry.get("latency", 0) or 0
                    status = entry.get("response", {}).get("status", 0)
                except json.JSONDecodeError:
                    # Try nginx access log format:
                    # IP - - [15/May/2026:12:28:13 +0200] host "METHOD /path HTTP/1.1" status ...
                    import re
                    ts_match = re.search(r'\[(\d{2}/\w{3}/\d{4}):(\d{2}:\d{2}):\d{2}', line)
                    status_match = re.search(r'" (\d{3}) ', line)
                    if not ts_match:
                        continue
                    try:
                        date_str = ts_match.group(1)  # "15/May/2026"
                        time_str = ts_match.group(2)  # "12:28"
                        ts_local = datetime.strptime(f"{date_str} {time_str}", "%d/%b/%Y %H:%M")
                    except ValueError:
                        continue
                    latency = 0
                    status = int(status_match.group(1)) if status_match else 0

                # Filter by date
                if ts_local.date() != target_date:
                    continue

                # Filter by time range
                ts_time = ts_local.strftime("%H:%M")
                if ts_time < time_from or ts_time > time_to:
                    continue

                # Group by minute
                minute_key = ts_local.strftime("%H:%M")

                per_minute[minute_key]["count"] += 1
                per_minute[minute_key]["total_latency"] += latency
                per_minute[minute_key]["statuses"][str(status)] += 1
                total_requests += 1
                total_latency += latency

        except Exception as exc:
            logger.error("Error reading logs from pod %s: %s", pod_name, exc)
            continue

    # Sort by time
    sorted_minutes = sorted(per_minute.items())

    # Build result
    minutes_data = []
    for minute, data in sorted_minutes:
        avg_latency = data["total_latency"] / data["count"] if data["count"] > 0 else 0
        minutes_data.append({
            "time": minute,
            "count": data["count"],
            "avg_latency_ms": round(avg_latency, 1),
            "statuses": dict(data["statuses"]),
        })

    avg_total_latency = total_latency / total_requests if total_requests > 0 else 0

    return {
        "route_id": route_id,
        "date": date,
        "time_from": time_from,
        "time_to": time_to,
        "total_requests": total_requests,
        "avg_latency_ms": round(avg_total_latency, 1),
        "peak_per_minute": max((m["count"] for m in minutes_data), default=0),
        "minutes": minutes_data,
        "pods_queried": APISIX_PODS,
        "log_file": log_file,
    }


def get_available_routes() -> List[Dict]:
    """Return the list of routes with their log file mappings."""
    return [
        {"route_id": route_id, "log_file": log_file, "name": ROUTE_NAMES.get(route_id, route_id)}
        for route_id, log_file in LOG_FILES.items()
    ]
