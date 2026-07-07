"""Authentication router: login, logout, me."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserInfo
from app.services.auth_service import (
    authenticate_user,
    bearer_scheme,
    blacklist_token,
    create_access_token,
    get_current_user,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(request.username, request.password, db)
    if not user:
        # Log failed login attempt
        from app.services.audit_service import log_action
        log_action(db, request.username, "LOGIN", status="failed", details="Invalid credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token({"sub": user.username, "role": user.role})
    # Log successful login
    from app.services.audit_service import log_action
    log_action(db, user.username, "LOGIN", status="success")
    logger.info("User '%s' logged in.", user.username)
    return TokenResponse(access_token=token)


@router.post("/auth/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = jwt.decode(
        credentials.credentials,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        blacklist_token(jti, expires_at, db)
    # Log logout
    from app.services.audit_service import log_action
    log_action(db, current_user.username, "LOGOUT")
    logger.info("User '%s' logged out.", current_user.username)
    return {"detail": "Logged out successfully"}


@router.get("/auth/me", response_model=UserInfo)
def me(current_user: User = Depends(get_current_user)):
    return UserInfo(
        username=current_user.username,
        role=current_user.role,
        is_active=current_user.is_active,
    )
