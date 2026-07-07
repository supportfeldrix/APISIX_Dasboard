"""Kubernetes/OpenShift API service for pod information and resource usage."""
import logging
import os
from typing import List, Dict, Any

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

# Path to the auto-mounted service account token inside a pod
SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def _get_token() -> str:
    """Get the K8s API token — prefer SA token mounted in pod, fall back to config."""
    # First try the mounted service account token (works inside OpenShift pods)
    if os.path.exists(SA_TOKEN_PATH):
        with open(SA_TOKEN_PATH, "r") as f:
            return f.read().strip()
    # Fall back to configured token
    return settings.OC_TOKEN


def _get_api_server() -> str:
    """Get the K8s API server URL — prefer in-cluster, fall back to config."""
    # Inside a pod, the API server is always at this address
    if os.path.exists(SA_TOKEN_PATH):
        return "https://kubernetes.default.svc"
    return settings.OC_API_SERVER


def _get_headers() -> dict:
    """Get authorization headers for the K8s API."""
    token = _get_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _get_client() -> httpx.Client:
    """Create an httpx client for K8s API calls."""
    api_server = _get_api_server()
    verify = SA_CA_PATH if os.path.exists(SA_CA_PATH) else settings.OC_VERIFY_SSL
    return httpx.Client(
        base_url=api_server,
        headers=_get_headers(),
        verify=verify,
        timeout=10,
    )


def get_pods() -> List[Dict[str, Any]]:
    """Fetch all pods in the configured namespace."""
    if not _get_token():
        raise HTTPException(
            status_code=503,
            detail="OpenShift API not configured (no SA token or OC_TOKEN)",
        )

    namespace = settings.OC_NAMESPACE
    url = f"/api/v1/namespaces/{namespace}/pods"

    try:
        with _get_client() as client:
            response = client.get(url)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("K8s API unreachable: %s", e)
        raise HTTPException(status_code=503, detail="OpenShift API unreachable")

    if response.status_code != 200:
        logger.error("K8s API returned %d: %s", response.status_code, response.text[:200])
        raise HTTPException(
            status_code=502,
            detail=f"OpenShift API returned {response.status_code}",
        )

    data = response.json()
    pods = []

    for item in data.get("items", []):
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})

        # Get container resource requests/limits
        containers = []
        for container in spec.get("containers", []):
            resources = container.get("resources", {})
            containers.append({
                "name": container.get("name", ""),
                "image": container.get("image", "").split("/")[-1],  # short image name
                "requests": resources.get("requests", {}),
                "limits": resources.get("limits", {}),
            })

        # Get container statuses
        container_statuses = []
        for cs in status.get("containerStatuses", []):
            container_statuses.append({
                "name": cs.get("name", ""),
                "ready": cs.get("ready", False),
                "restarts": cs.get("restartCount", 0),
                "state": list(cs.get("state", {}).keys())[0] if cs.get("state") else "unknown",
            })

        pods.append({
            "name": metadata.get("name", ""),
            "namespace": metadata.get("namespace", ""),
            "phase": status.get("phase", "Unknown"),
            "node": spec.get("nodeName", ""),
            "start_time": status.get("startTime", ""),
            "ip": status.get("podIP", ""),
            "containers": containers,
            "container_statuses": container_statuses,
            "labels": metadata.get("labels", {}),
        })

    return pods


def get_pod_metrics() -> List[Dict[str, Any]]:
    """Fetch pod resource usage (CPU/memory) from the metrics API."""
    if not _get_token():
        raise HTTPException(
            status_code=503,
            detail="OpenShift API not configured (no SA token or OC_TOKEN)",
        )

    namespace = settings.OC_NAMESPACE
    url = f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods"

    try:
        with _get_client() as client:
            response = client.get(url)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("K8s Metrics API unreachable: %s", e)
        raise HTTPException(status_code=503, detail="OpenShift Metrics API unreachable")

    if response.status_code != 200:
        logger.error("K8s Metrics API returned %d: %s", response.status_code, response.text[:200])
        raise HTTPException(
            status_code=502,
            detail=f"OpenShift Metrics API returned {response.status_code}",
        )

    data = response.json()
    pod_metrics = []

    for item in data.get("items", []):
        metadata = item.get("metadata", {})
        containers = []
        total_cpu_millicores = 0
        total_memory_bytes = 0

        for container in item.get("containers", []):
            usage = container.get("usage", {})
            cpu_str = usage.get("cpu", "0")
            mem_str = usage.get("memory", "0")

            # Parse CPU (e.g., "250m" -> 250, "1" -> 1000)
            cpu_millicores = _parse_cpu(cpu_str)
            # Parse memory (e.g., "128Mi" -> bytes)
            memory_bytes = _parse_memory(mem_str)

            total_cpu_millicores += cpu_millicores
            total_memory_bytes += memory_bytes

            containers.append({
                "name": container.get("name", ""),
                "cpu_millicores": cpu_millicores,
                "memory_bytes": memory_bytes,
                "memory_mi": round(memory_bytes / (1024 * 1024), 1),
            })

        pod_metrics.append({
            "name": metadata.get("name", ""),
            "timestamp": item.get("timestamp", ""),
            "total_cpu_millicores": total_cpu_millicores,
            "total_memory_bytes": total_memory_bytes,
            "total_memory_mi": round(total_memory_bytes / (1024 * 1024), 1),
            "containers": containers,
        })

    return pod_metrics


def _parse_cpu(cpu_str: str) -> int:
    """Parse Kubernetes CPU string to millicores (e.g., '250m' -> 250, '1' -> 1000)."""
    if not cpu_str:
        return 0
    cpu_str = str(cpu_str)
    if cpu_str.endswith("n"):
        return int(int(cpu_str[:-1]) / 1_000_000)
    elif cpu_str.endswith("u"):
        return int(int(cpu_str[:-1]) / 1_000)
    elif cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    else:
        return int(float(cpu_str) * 1000)


def _parse_memory(mem_str: str) -> int:
    """Parse Kubernetes memory string to bytes (e.g., '128Mi' -> 134217728)."""
    if not mem_str:
        return 0
    mem_str = str(mem_str)
    if mem_str.endswith("Ki"):
        return int(mem_str[:-2]) * 1024
    elif mem_str.endswith("Mi"):
        return int(mem_str[:-2]) * 1024 * 1024
    elif mem_str.endswith("Gi"):
        return int(float(mem_str[:-2]) * 1024 * 1024 * 1024)
    elif mem_str.endswith("Ti"):
        return int(float(mem_str[:-2]) * 1024 * 1024 * 1024 * 1024)
    elif mem_str.endswith("k"):
        return int(mem_str[:-1]) * 1000
    elif mem_str.endswith("M"):
        return int(mem_str[:-1]) * 1000 * 1000
    elif mem_str.endswith("G"):
        return int(float(mem_str[:-1]) * 1000 * 1000 * 1000)
    else:
        return int(mem_str)


def delete_pod(pod_name: str) -> Dict[str, Any]:
    """Delete a pod in the configured namespace (triggers restart by controller).

    Args:
        pod_name: Name of the pod to delete.

    Returns:
        Dict with status information.

    Raises:
        HTTPException: If the pod cannot be deleted or API is unreachable.
    """
    if not _get_token():
        raise HTTPException(
            status_code=503,
            detail="OpenShift API not configured (no SA token or OC_TOKEN)",
        )

    namespace = settings.OC_NAMESPACE
    url = f"/api/v1/namespaces/{namespace}/pods/{pod_name}"

    try:
        with _get_client() as client:
            response = client.delete(url)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("K8s API unreachable when deleting pod %s: %s", pod_name, e)
        raise HTTPException(status_code=503, detail="OpenShift API unreachable")

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Pod not found: {pod_name}")

    if response.status_code >= 300:
        logger.error(
            "K8s API returned %d when deleting pod %s: %s",
            response.status_code, pod_name, response.text[:200],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to delete pod: {response.status_code}",
        )

    logger.info("Pod %s deleted (restart triggered)", pod_name)
    return {"pod": pod_name, "status": "deleted", "message": "Pod will be restarted by its controller"}
