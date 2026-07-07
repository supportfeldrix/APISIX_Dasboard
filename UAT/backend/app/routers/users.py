"""Users router — admin-only user management (role changes, deletion)."""
import re
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.auth_service import get_current_user

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")

logger = logging.getLogger(__name__)
router = APIRouter()


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class RoleUpdateRequest(BaseModel):
    role: str  # "admin" or "viewer"


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


@router.get("/users", response_model=List[UserResponse])
def list_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all users. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    users = db.query(User).all()
    return users


@router.put("/users/{username}/role")
def update_user_role(
    username: str,
    body: RoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a user's role. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if body.role not in ("admin", "viewer"):
        raise HTTPException(status_code=422, detail="Role must be 'admin' or 'viewer'")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    # Prevent removing the last admin
    if user.role == "admin" and body.role == "viewer":
        admin_count = db.query(User).filter(User.role == "admin", User.is_active == True).count()
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last admin user",
            )

    user.role = body.role
    db.commit()
    logger.info("User '%s' role changed to '%s' by '%s'", username, body.role, current_user.username)
    return {"message": f"User '{username}' role updated to '{body.role}'"}


@router.put("/users/{username}/active")
def toggle_user_active(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle a user's active status. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    # Prevent deactivating yourself
    if user.username == current_user.username:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user.is_active = not user.is_active
    db.commit()
    status = "activated" if user.is_active else "deactivated"
    logger.info("User '%s' %s by '%s'", username, status, current_user.username)
    return {"message": f"User '{username}' {status}"}


@router.post("/users", response_model=UserResponse)
def create_user(
    body: UserCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new local user. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if body.role not in ("admin", "viewer"):
        raise HTTPException(status_code=422, detail="Role must be 'admin' or 'viewer'")

    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"User '{body.username}' already exists")

    from app.services.auth_service import hash_password
    new_user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info("User '%s' created with role '%s' by '%s'", body.username, body.role, current_user.username)
    return new_user


@router.delete("/users/{username}")
def delete_user(
    username: str = Path(..., pattern=r"^[a-zA-Z0-9._-]{1,128}$"),
    *,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete a user account. Admin only."""
    client_ip = request.client.host if request.client else None

    # Guard 1: Admin role check (403 — no audit for unauthenticated/non-admin)
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Guard 2: Username format validation
    if not USERNAME_PATTERN.match(username):
        _audit_failed(db, current_user.username, username, "Invalid username format", client_ip)
        raise HTTPException(status_code=400, detail="Invalid username format")

    # Guard 3: Self-delete check
    if username == current_user.username:
        _audit_failed(db, current_user.username, username, "Cannot delete your own account", client_ip)
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    # Guard 4: User existence check
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        _audit_failed(db, current_user.username, username, f"User '{username}' not found", client_ip)
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    # Guard 5: Last admin check
    if target_user.role == "admin":
        admin_count = db.query(User).filter(User.role == "admin", User.is_active == True).count()
        if admin_count <= 1:
            _audit_failed(db, current_user.username, username, "Cannot delete the last admin user", client_ip)
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last admin user",
            )

    # Success path: audit entry + delete in a single atomic commit
    audit_entry = AuditLog(
        timestamp=datetime.now(timezone.utc),
        username=current_user.username,
        action="DELETE",
        resource_type="users",
        resource_id=username,
        details=None,
        ip_address=client_ip,
        status="success",
    )
    db.add(audit_entry)
    db.delete(target_user)
    db.commit()
    logger.info("User '%s' deleted by '%s'", username, current_user.username)
    return {"message": f"User '{username}' deleted successfully"}


def _audit_failed(
    db: Session,
    actor: str,
    target_username: str,
    reason: str,
    ip_address: str | None,
) -> None:
    """Persist a failed audit log entry before raising an HTTPException."""
    entry = AuditLog(
        timestamp=datetime.now(timezone.utc),
        username=actor,
        action="DELETE",
        resource_type="users",
        resource_id=target_username,
        details=reason,
        ip_address=ip_address,
        status="failed",
    )
    db.add(entry)
    db.commit()
