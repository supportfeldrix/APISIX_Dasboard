"""Unit tests for auth_service."""
import pytest
from datetime import datetime, timezone, timedelta
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    verify_token,
    authenticate_user,
    blacklist_token,
    seed_admin,
)
from app.models.user import User
from app.models.token_blacklist import TokenBlacklist
from jose import jwt
from app.config import settings


def test_hash_password_is_not_plaintext():
    hashed = hash_password("MySecret123")
    assert hashed != "MySecret123"
    assert hashed.startswith("$2b$")


def test_verify_password_correct():
    hashed = hash_password("MySecret123")
    assert verify_password("MySecret123", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("MySecret123")
    assert verify_password("WrongPassword", hashed) is False


def test_create_access_token_decodable():
    token = create_access_token({"sub": "admin", "role": "admin"})
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "admin"
    assert payload["role"] == "admin"
    assert "jti" in payload
    assert "exp" in payload


def test_create_access_token_has_jti():
    token1 = create_access_token({"sub": "admin"})
    token2 = create_access_token({"sub": "admin"})
    p1 = jwt.decode(token1, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    p2 = jwt.decode(token2, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert p1["jti"] != p2["jti"]  # Each token gets a unique JTI


def test_verify_token_valid(db_session):
    token = create_access_token({"sub": "admin", "role": "admin"})
    payload = verify_token(token, db_session)
    assert payload["sub"] == "admin"


def test_verify_token_invalid_raises(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        verify_token("not.a.valid.token", db_session)
    assert exc.value.status_code == 401


def test_verify_token_blacklisted_raises(db_session):
    from fastapi import HTTPException
    token = create_access_token({"sub": "admin"})
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    jti = payload["jti"]
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    blacklist_token(jti, exp, db_session)
    with pytest.raises(HTTPException) as exc:
        verify_token(token, db_session)
    assert exc.value.status_code == 401


def test_authenticate_user_valid(db_session, admin_user):
    result = authenticate_user("testadmin", "TestPass123!", db_session)
    assert result is not None
    assert result.username == "testadmin"


def test_authenticate_user_wrong_password(db_session, admin_user):
    result = authenticate_user("testadmin", "WrongPassword", db_session)
    assert result is None


def test_authenticate_user_nonexistent(db_session):
    result = authenticate_user("nobody", "password", db_session)
    assert result is None


def test_seed_admin_creates_user(db_session):
    seed_admin(db_session)
    user = db_session.query(User).filter(User.username == "admin").first()
    assert user is not None
    assert user.role == "admin"
    assert verify_password("N03ntry#", user.hashed_password)


def test_seed_admin_skips_if_users_exist(db_session, admin_user):
    seed_admin(db_session)
    count = db_session.query(User).count()
    assert count == 1  # Only the fixture user, no extra admin created


def test_blacklist_token_persists(db_session):
    jti = "test-jti-12345"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    blacklist_token(jti, expires_at, db_session)
    entry = db_session.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first()
    assert entry is not None
    assert entry.jti == jti
