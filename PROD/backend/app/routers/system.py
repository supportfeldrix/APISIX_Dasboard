"""System info router — version, dependencies, and health for audit compliance."""
import logging
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException

from app.models.user import User
from app.schemas.version_check import VersionCheckResponse
from app.services.auth_service import get_current_user
from app.services.version_check_service import version_check_service
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Application version — update this on each release
APP_VERSION = "1.0.0"
APP_BUILD_DATE = "2026-05-08"
APP_CHANGELOG = [
    {
        "version": "1.0.0",
        "date": "2026-05-08",
        "changes": [
            "Initial release",
            "APISIX Admin API proxy with role-based access control",
            "Route, Service, Upstream, Consumer, Plugin, SSL management",
            "LDAP authentication with auto-provisioning",
            "Pod monitoring with CPU/memory metrics from OpenShift",
            "APISIX Prometheus metrics (connections, bandwidth, HTTP status)",
            "User management with admin/viewer roles",
            "YAML/JSON editor with Monaco Editor",
            "Responsive UI with Tailwind CSS",
        ],
    },
]


def _get_installed_packages() -> List[Dict[str, str]]:
    """Read installed package versions from requirements or pip."""
    packages = []
    req_file = Path(__file__).parent.parent.parent / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if ">=" in line:
                    name, version = line.split(">=", 1)
                    packages.append({"name": name.strip(), "version": f">={version.strip()}"})
                elif "==" in line:
                    name, version = line.split("==", 1)
                    packages.append({"name": name.strip(), "version": version.strip()})
                else:
                    packages.append({"name": line, "version": "latest"})
    return packages

import os

@router.get("/system/info")
def get_system_info(current_user: User = Depends(get_current_user)):
    """Return system information for audit and compliance."""
    return {
        "application": {
            "name": "CRO IT APISIX Dashboard",
            "version": APP_VERSION,
            "build_date": APP_BUILD_DATE,
            "environment": os.environ.get("APP_ENVIRONMENT", "PROD"),
            "description": "Custom APISIX API Gateway management dashboard",
            "owner": "CRO IT",
            "contact": "CRO IT Team",
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
        },
        "integrations": {
            "apisix_admin_url": settings.APISIX_ADMIN_BASE_URL,
            "apisix_metrics_url": settings.APISIX_METRICS_URL,
            "ldap_enabled": settings.LDAP_ENABLED,
            "ldap_server": settings.LDAP_SERVER if settings.LDAP_ENABLED else "N/A",
            "openshift_api": settings.OC_API_SERVER or "Not configured",
            "openshift_namespace": settings.OC_NAMESPACE,
        },
        "security": {
            "jwt_algorithm": settings.JWT_ALGORITHM,
            "jwt_expiry_minutes": settings.JWT_EXPIRY_MINUTES,
            "ssl_verification": settings.APISIX_ADMIN_VERIFY_SSL,
            "ldap_ssl": settings.LDAP_USE_SSL if settings.LDAP_ENABLED else "N/A",
            "cors_origins": settings.CORS_ORIGINS,
        },
    }


@router.get("/system/dependencies")
def get_dependencies(current_user: User = Depends(get_current_user)):
    """Return installed dependency versions for security patching audit."""
    return {
        "backend_dependencies": _get_installed_packages(),
        "python_version": platform.python_version(),
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/system/changelog")
def get_changelog(current_user: User = Depends(get_current_user)):
    """Return application changelog/release history."""
    return {
        "current_version": APP_VERSION,
        "releases": APP_CHANGELOG,
    }


@router.get("/system/version-check", response_model=VersionCheckResponse)
def get_version_check_status(current_user: User = Depends(get_current_user)):
    """Return the current APISIX version check status.

    Retrieves the latest version check result from the database and returns
    it as a VersionCheckResponse. If no result exists yet, returns a response
    with null versions and check_successful=False.
    """
    result = version_check_service.get_latest_result()

    if result is None:
        return VersionCheckResponse(
            running_version=None,
            latest_version=None,
            update_available=False,
            last_checked=datetime.now(timezone.utc).isoformat(),
            check_successful=False,
            error_message="No version check has been performed yet",
        )

    return VersionCheckResponse(
        running_version=result.running_version,
        latest_version=result.latest_version,
        update_available=result.update_available,
        last_checked=result.check_timestamp.isoformat(),
        check_successful=result.check_successful,
        error_message=result.error_message,
    )


@router.post("/system/version-check/trigger", response_model=VersionCheckResponse)
async def trigger_version_check(current_user: User = Depends(get_current_user)):
    """Manually trigger a version check. Admin only.

    Runs a full version check cycle (queries APISIX Admin API and GitHub
    Releases API), persists the result, and returns it.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await version_check_service.run_check()

    return VersionCheckResponse(
        running_version=result.running_version,
        latest_version=result.latest_version,
        update_available=result.update_available,
        last_checked=result.check_timestamp.isoformat(),
        check_successful=result.check_successful,
        error_message=result.error_message,
    )
