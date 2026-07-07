"""Property-based tests for the APISIX Admin API proxy."""
import logging
import json

import pytest
import respx
import httpx
from hypothesis import given, settings as h_settings, assume, HealthCheck
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings as app_settings
from app.database import Base, get_db
from app.models.user import User
from app.models.token_blacklist import TokenBlacklist  # noqa: F401 — ensure table registered
from app.services.auth_service import hash_password, create_access_token
from app.services.proxy_service import ALLOWED_RESOURCES
from app.main import app


# ---------------------------------------------------------------------------
# Test database setup — use StaticPool to share a single in-memory SQLite
# connection across all sessions (avoids the "no such table" issue with
# multiple connections to :memory:).
# ---------------------------------------------------------------------------

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=_test_engine)
_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

# Seed test users
_db = _TestSessionLocal()
_db.add(User(
    username="prop_viewer",
    hashed_password=hash_password("ViewerPass1!"),
    role="viewer",
    is_active=True,
))
_db.add(User(
    username="prop_admin",
    hashed_password=hash_password("AdminPass1!"),
    role="admin",
    is_active=True,
))
_db.commit()
_db.close()

# Generate tokens for the seeded users
_viewer_token = create_access_token({"sub": "prop_viewer", "role": "viewer"})
_admin_token = create_access_token({"sub": "prop_admin", "role": "admin"})

# Create test client
client = TestClient(app)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

non_get_methods = st.sampled_from(["POST", "PUT", "PATCH", "DELETE"])
all_methods = st.sampled_from(["GET", "POST", "PUT", "PATCH", "DELETE"])
allowed_resources = st.sampled_from(sorted(ALLOWED_RESOURCES))

# Strategy for proxy scenarios (resource + method + optional sub_path)
proxy_request_strategy = st.fixed_dictionaries({
    "method": all_methods,
    "resource_type": allowed_resources,
    "sub_path": st.from_regex(r"[a-zA-Z0-9_\-]{0,20}", fullmatch=True),
})


# ---------------------------------------------------------------------------
# Property 4: Viewer role blocks all non-GET requests
# Feature: apisix-dashboard, Property 4: Viewer role blocks all non-GET requests
# ---------------------------------------------------------------------------
# Validates: Requirements 2.2, 2.3

@given(method=non_get_methods, resource=allowed_resources)
@h_settings(max_examples=25, deadline=None)
def test_property_4_viewer_blocks_non_get(method, resource):
    """Property 4: Viewer role blocks all non-GET requests."""
    headers = {"Authorization": f"Bearer {_viewer_token}"}
    url = f"/api/apisix/{resource}"
    response = client.request(method, url, headers=headers)
    assert response.status_code == 403, (
        f"Viewer with {method} on {resource} should get 403, got {response.status_code}"
    )
    assert "Insufficient permissions" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Property 5: Admin role permits all CRUD operations
# Feature: apisix-dashboard, Property 5: Admin role permits all CRUD operations
# ---------------------------------------------------------------------------
# Validates: Requirements 2.4

@given(method=all_methods, resource=allowed_resources)
@h_settings(max_examples=25, deadline=None)
@respx.mock
def test_property_5_admin_permits_all_crud(method, resource):
    """Property 5: Admin role permits all CRUD operations."""
    headers = {"Authorization": f"Bearer {_admin_token}", "Content-Type": "application/json"}

    # Mock the APISIX Admin API to return 200 for any request
    respx.route(
        method=method,
        url__startswith=f"{app_settings.APISIX_ADMIN_BASE_URL}/apisix/admin/{resource}",
    ).mock(return_value=httpx.Response(200, json={"status": "ok"}))

    url = f"/api/apisix/{resource}"
    body = json.dumps({"name": "test"}) if method != "GET" else None
    response = client.request(method, url, headers=headers, content=body)

    # Admin should never get 403
    assert response.status_code != 403, (
        f"Admin with {method} on {resource} should NOT get 403"
    )


# ---------------------------------------------------------------------------
# Property 6: Unauthenticated requests are always rejected
# Feature: apisix-dashboard, Property 6: Unauthenticated requests are always rejected
# ---------------------------------------------------------------------------
# Validates: Requirements 2.5, 1.5

@given(resource=allowed_resources, method=all_methods)
@h_settings(max_examples=25, deadline=None)
def test_property_6_unauthenticated_rejected(resource, method):
    """Property 6: Unauthenticated requests are always rejected with 401/403."""
    url = f"/api/apisix/{resource}"
    # No Authorization header
    response = client.request(method, url)
    # FastAPI's HTTPBearer returns 403 when no credentials are provided
    assert response.status_code in (401, 403), (
        f"Unauthenticated {method} on {resource} should get 401/403, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Property 7: Proxy responses never contain sensitive credentials
# Feature: apisix-dashboard, Property 7: Proxy responses never contain sensitive credentials
# ---------------------------------------------------------------------------
# Validates: Requirements 2.6, 12.2

@given(
    data=st.fixed_dictionaries({
        "method": all_methods,
        "resource": allowed_resources,
        "response_body": st.text(min_size=0, max_size=500),
    })
)
@h_settings(max_examples=25, deadline=None)
@respx.mock
def test_property_7_responses_never_contain_credentials(data):
    """Property 7: Proxy responses never contain APISIX_ADMIN_KEY value."""
    headers = {"Authorization": f"Bearer {_admin_token}", "Content-Type": "application/json"}

    method = data["method"]
    resource = data["resource"]
    mock_body = data["response_body"]

    respx.route(
        method=method,
        url__startswith=f"{app_settings.APISIX_ADMIN_BASE_URL}/apisix/admin/{resource}",
    ).mock(return_value=httpx.Response(200, text=mock_body))

    url = f"/api/apisix/{resource}"
    body = json.dumps({"name": "test"}) if method != "GET" else None
    response = client.request(method, url, headers=headers, content=body)

    # The APISIX_ADMIN_KEY value must never appear in the response
    admin_key = app_settings.APISIX_ADMIN_KEY
    assert admin_key not in response.text, (
        "Response body should never contain the APISIX_ADMIN_KEY value"
    )
    # Check headers too
    for header_value in response.headers.values():
        assert admin_key not in header_value, (
            "Response headers should never contain the APISIX_ADMIN_KEY value"
        )


# ---------------------------------------------------------------------------
# Property 9: Path allowlist is enforced for all requests
# Feature: apisix-dashboard, Property 9: Path allowlist is enforced for all requests
# ---------------------------------------------------------------------------
# Validates: Requirements 3.4

@given(path=st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-/"),
))
@h_settings(max_examples=25, deadline=None)
@respx.mock
def test_property_9_path_allowlist_enforced(path):
    """Property 9: Path allowlist is enforced for all requests."""
    headers = {"Authorization": f"Bearer {_admin_token}"}

    # Mock all allowed resources to return 200
    for resource in ALLOWED_RESOURCES:
        respx.route(
            url__startswith=f"{app_settings.APISIX_ADMIN_BASE_URL}/apisix/admin/{resource}",
        ).mock(return_value=httpx.Response(200, json={"ok": True}))

    url = f"/api/apisix/{path}"
    response = client.get(url, headers=headers)

    # The first path segment is the resource_type in the URL pattern
    first_segment = path.split("/")[0] if "/" in path else path

    if first_segment in ALLOWED_RESOURCES:
        # Should NOT get 400 for path validation (may get 200 from mock)
        assert response.status_code != 400 or "not permitted" not in response.json().get("detail", ""), (
            f"Allowed resource '{first_segment}' should not be rejected by path allowlist"
        )
    else:
        # Should get 400 (resource not permitted) or 404 (route not matched by FastAPI)
        assert response.status_code in (400, 404, 422), (
            f"Disallowed path '{path}' should be rejected, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Property 10: Non-2xx Admin API responses are forwarded unchanged
# Feature: apisix-dashboard, Property 10: Non-2xx Admin API responses are forwarded unchanged
# ---------------------------------------------------------------------------
# Validates: Requirements 3.2

@given(status_code=st.integers(min_value=400, max_value=599))
@h_settings(max_examples=25, deadline=None)
@respx.mock
def test_property_10_non_2xx_forwarded_unchanged(status_code):
    """Property 10: Non-2xx Admin API responses are forwarded unchanged."""
    headers = {"Authorization": f"Bearer {_admin_token}"}

    error_body = {"error_msg": f"Error with status {status_code}"}
    respx.get(
        url=f"{app_settings.APISIX_ADMIN_BASE_URL}/apisix/admin/routes",
    ).mock(return_value=httpx.Response(status_code, json=error_body))

    response = client.get("/api/apisix/routes", headers=headers)

    # The status code from APISIX should be forwarded unchanged
    assert response.status_code == status_code, (
        f"Expected status {status_code} to be forwarded, got {response.status_code}"
    )
    # The body should be forwarded unchanged
    assert response.json() == error_body


# ---------------------------------------------------------------------------
# Property 11: Every proxied request produces a log entry with required fields
# Feature: apisix-dashboard, Property 11: Every proxied request produces a log entry with required fields
# ---------------------------------------------------------------------------
# Validates: Requirements 3.5

@given(scenario=proxy_request_strategy)
@h_settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@respx.mock
def test_property_11_every_proxy_request_produces_log(scenario, caplog):
    """Property 11: Every proxied request produces a log entry with required fields."""
    headers = {"Authorization": f"Bearer {_admin_token}", "Content-Type": "application/json"}

    method = scenario["method"]
    resource = scenario["resource_type"]
    sub_path = scenario["sub_path"]

    respx.route(
        method=method,
        url__startswith=f"{app_settings.APISIX_ADMIN_BASE_URL}/apisix/admin/{resource}",
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    url = f"/api/apisix/{resource}"
    if sub_path:
        url = f"{url}/{sub_path}"

    body = json.dumps({"name": "test"}) if method != "GET" else None

    with caplog.at_level(logging.INFO, logger="app.services.proxy_service"):
        response = client.request(method, url, headers=headers, content=body)

    # Only check log if the request was actually proxied (not rejected)
    if response.status_code not in (403, 401):
        proxy_records = [r for r in caplog.records if r.name == "app.services.proxy_service"]
        assert len(proxy_records) >= 1, "Expected at least one log entry for proxied request"
        log_message = proxy_records[-1].message
        assert "PROXY" in log_message, f"Log should contain 'PROXY', got: {log_message}"
        assert "prop_admin" in log_message, f"Log should contain username"
        assert method.upper() in log_message, f"Log should contain HTTP method"
        assert resource in log_message, f"Log should contain resource type"
        assert "ms" in log_message, f"Log should contain duration in ms"
