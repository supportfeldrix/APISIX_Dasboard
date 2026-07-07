"""APISIX Admin API proxy router."""
import json as _json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.audit_service import log_action
from app.services.proxy_service import forward_request
from app.utils.pem_validator import validate_pem_cert, validate_pem_key

logger = logging.getLogger(__name__)
router = APIRouter()


@router.api_route(
    "/apisix/{resource_type}/{sub_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
@router.api_route(
    "/apisix/{resource_type}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy(
    resource_type: str,
    request: Request,
    sub_path: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Proxy all APISIX Admin API requests through the backend."""
    # Enforce viewer role — read-only
    if current_user.role == "viewer" and request.method.upper() != "GET":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    body = await request.body()
    content_type = request.headers.get("content-type", "application/json")

    # SSL PEM validation for PUT/POST requests
    if resource_type == "ssl" and request.method.upper() in ("PUT", "POST"):
        try:
            payload = _json.loads(body)
            cert = payload.get("cert", "")
            key = payload.get("key", "")
            if not validate_pem_cert(cert):
                raise HTTPException(status_code=422, detail="Invalid PEM certificate format")
            if not validate_pem_key(key):
                raise HTTPException(status_code=422, detail="Invalid PEM private key format")
        except (_json.JSONDecodeError, UnicodeDecodeError):
            pass  # Let the Admin API handle malformed JSON

    apisix_response = forward_request(
        method=request.method,
        resource_type=resource_type,
        sub_path=sub_path,
        body=body or None,
        query_params=dict(request.query_params),
        content_type=content_type,
        username=current_user.username,
    )

    # Audit log for write operations (POST, PUT, PATCH, DELETE)
    method_upper = request.method.upper()
    if method_upper != "GET":
        action_map = {
            "POST": "CREATE",
            "PUT": "UPDATE",
            "PATCH": "UPDATE",
            "DELETE": "DELETE",
        }
        action = action_map.get(method_upper, method_upper)
        resource_id = sub_path or None
        audit_status = "success" if apisix_response.status_code < 400 else "failed"

        # Extract resource name from body for better audit detail
        details = None
        if body and method_upper in ("POST", "PUT", "PATCH"):
            try:
                payload = _json.loads(body)
                name = payload.get("name") or payload.get("username") or ""
                if name:
                    details = f"name={name}"
            except (_json.JSONDecodeError, UnicodeDecodeError):
                pass

        try:
            log_action(
                db=db,
                username=current_user.username,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=request.headers.get("x-real-ip", request.client.host if request.client else None),
                status=audit_status,
            )
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)

    return Response(
        content=apisix_response.content,
        status_code=apisix_response.status_code,
        media_type=apisix_response.headers.get("content-type", "application/json"),
    )
