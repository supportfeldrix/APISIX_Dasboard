"""Pods router — exposes OpenShift pod information and resource usage."""
import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException

from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.k8s_service import get_pods, get_pod_metrics, delete_pod
from app.services.audit_service import log_action
from app.database import get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/pods")
def list_pods(current_user: User = Depends(get_current_user)):
    """List all pods in the configured namespace with their status."""
    return {"pods": get_pods()}


@router.get("/pods/metrics")
def list_pod_metrics(current_user: User = Depends(get_current_user)):
    """Get CPU and memory usage for all pods in the namespace."""
    return {"pod_metrics": get_pod_metrics()}


@router.delete("/pods/{pod_name}")
def restart_pod(
    pod_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete (restart) a pod. The deployment controller will recreate it.

    This is equivalent to 'oc delete pod <name>' — the pod's owning
    controller (Deployment/StatefulSet) will automatically create a replacement.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required to restart pods")

    result = delete_pod(pod_name)
    logger.info("Pod '%s' restarted by user '%s'", pod_name, current_user.username)

    # Audit log
    log_action(
        db=db,
        username=current_user.username,
        action="POD_RESTART",
        resource_type="pod",
        resource_id=pod_name,
        details=f"Pod deleted/restarted: {pod_name}",
        status="success",
    )

    return result
