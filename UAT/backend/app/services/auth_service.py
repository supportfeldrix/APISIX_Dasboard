"""Authentication service: JWT creation/validation, bcrypt, seeding."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.token_blacklist import TokenBlacklist
from app.models.user import User

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    pwd_bytes = password.encode("utf-8")[:72]  # bcrypt max 72 bytes
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        pwd_bytes = plain.encode("utf-8")[:72]
        hashed_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hashed_bytes)
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    """Create a signed JWT with a UUID4 JTI claim."""
    payload = data.copy()
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)
    payload.update({"jti": jti, "exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str, db: Session) -> dict:
    """Decode and validate a JWT; check it is not blacklisted."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise credentials_exception

    jti: Optional[str] = payload.get("jti")
    if jti is None:
        raise credentials_exception

    # Check blacklist
    blacklisted = db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first()
    if blacklisted:
        raise credentials_exception

    return payload


def authenticate_user(username: str, password: str, db: Session) -> Optional[User]:
    """Return the User if credentials are valid, else None.
    
    Tries local database auth first for known users, then LDAP.
    LDAP users are auto-created in the local DB with 'viewer' role on first login.
    """
    # Try local database authentication first (fast path for local accounts)
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if user and verify_password(password, user.hashed_password):
        logger.info("User '%s' authenticated via local database", username)
        return user

    # Skip LDAP for the built-in admin account (it's local-only)
    if username == "admin":
        logger.warning("Local auth failed for 'admin' — not trying LDAP")
        return None

    # Try LDAP authentication
    from app.services.ldap_service import authenticate_ldap
    ldap_result = authenticate_ldap(username, password)

    if ldap_result:
        # LDAP auth succeeded — find or create local user
        if not user:
            # Auto-create LDAP user with viewer role (admin can promote later)
            role = "admin" if ldap_result.get("is_admin") else "viewer"
            user = User(
                username=username,
                hashed_password=hash_password("__ldap_user__"),  # placeholder, not used for LDAP
                role=role,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info("LDAP user '%s' auto-created with role '%s'", username, role)
        elif not user.is_active:
            logger.warning("LDAP user '%s' is disabled in dashboard", username)
            return None

        return user

    # Neither local nor LDAP auth succeeded
    logger.info("Authentication failed for user '%s'", username)
    return None


def blacklist_token(jti: str, expires_at: datetime, db: Session) -> None:
    """Add a JTI to the blacklist to invalidate a token on logout."""
    entry = TokenBlacklist(jti=jti, expires_at=expires_at)
    db.add(entry)
    db.commit()


def seed_admin(db: Session) -> None:
    """Create the default admin user on first startup if no users exist."""
    if db.query(User).count() == 0:
        admin = User(
            username="admin",
            hashed_password=hash_password("N03ntry#"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        logger.info("Default admin user created.")
    else:
        logger.info("Admin seed skipped — users already exist.")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: decode JWT and return the current User."""
    payload = verify_token(credentials.credentials, db)
    username: Optional[str] = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user
