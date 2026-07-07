"""Property-based tests for authentication service."""
import pytest
from hypothesis import given, settings as h_settings, assume, HealthCheck
from hypothesis import strategies as st
from datetime import datetime, timezone, timedelta
from jose import jwt
from fastapi import HTTPException

from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    verify_token,
    blacklist_token,
)
from app.config import settings as app_settings


# Feature: apisix-dashboard, Property 1: Valid credentials always produce a decodable JWT
@given(
    sub=st.text(min_size=1, max_size=64, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-")),
    role=st.sampled_from(["viewer", "admin"]),
)
@h_settings(max_examples=100)
def test_property_1_valid_credentials_produce_decodable_jwt(sub, role):
    """Property 1: Valid credentials always produce a decodable JWT."""
    token = create_access_token({"sub": sub, "role": role})
    payload = jwt.decode(token, app_settings.JWT_SECRET, algorithms=[app_settings.JWT_ALGORITHM])
    assert payload["sub"] == sub
    assert payload["role"] == role
    assert "jti" in payload
    assert "exp" in payload


# Feature: apisix-dashboard, Property 2: Invalid credentials never produce a token
@given(
    username=st.text(min_size=1, max_size=64),
    password=st.text(min_size=1, max_size=72),
)
@h_settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_2_invalid_credentials_never_produce_token(db_session, username, password):
    """Property 2: Invalid credentials never produce a token for non-existent users."""
    from app.services.auth_service import authenticate_user
    # For any username/password combo where user doesn't exist, result is None
    result = authenticate_user(username, password, db_session)
    assert result is None


# Feature: apisix-dashboard, Property 3: Passwords are always stored as bcrypt hashes
# bcrypt requires: no null bytes, no surrogates, UTF-8 encoded length <= 72 bytes
@given(password=st.text(
    min_size=1,
    max_size=72,
    alphabet=st.characters(
        blacklist_characters="\x00",
        blacklist_categories=("Cs",),  # exclude surrogates
    ),
).filter(lambda p: len(p.encode("utf-8")) <= 72))
@h_settings(max_examples=100, deadline=None)
def test_property_3_passwords_stored_as_bcrypt_hashes(password):
    """Property 3: Passwords are always stored as bcrypt hashes, never plaintext."""
    hashed = hash_password(password)
    assert hashed != password
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password(password, hashed) is True


# Feature: apisix-dashboard, Property 14: Token logout invalidates the token for all subsequent requests
@given(sub=st.text(min_size=1, max_size=32, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))))
@h_settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_14_logout_invalidates_token(db_session, sub):
    """Property 14: Token logout invalidates the token for all subsequent requests."""
    token = create_access_token({"sub": sub, "role": "viewer"})
    payload = jwt.decode(token, app_settings.JWT_SECRET, algorithms=[app_settings.JWT_ALGORITHM])
    jti = payload["jti"]
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    # Token is valid before blacklisting
    result = verify_token(token, db_session)
    assert result["sub"] == sub

    # Blacklist the token (simulate logout)
    blacklist_token(jti, exp, db_session)

    # Token must be rejected after blacklisting
    with pytest.raises(HTTPException) as exc:
        verify_token(token, db_session)
    assert exc.value.status_code == 401
