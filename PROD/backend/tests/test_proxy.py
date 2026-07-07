"""Unit tests for proxy_service."""
import logging
import pytest
import respx
import httpx
from fastapi import HTTPException
from app.services.proxy_service import (
    ALLOWED_RESOURCES,
    forward_request,
    convert_body_if_yaml,
)


def test_allowed_resources_contains_expected():
    expected = {"routes", "services", "upstreams", "consumers", "plugins", "ssl", "global_rules", "plugin_metadata"}
    assert ALLOWED_RESOURCES == expected


def test_disallowed_resource_raises_400():
    with pytest.raises(HTTPException) as exc:
        forward_request("GET", "etcd", "", None, {}, "application/json", "testuser")
    assert exc.value.status_code == 400
    assert "not permitted" in exc.value.detail


@respx.mock
def test_forward_request_success():
    respx.get("http://mock-apisix:9180/apisix/admin/routes").mock(
        return_value=httpx.Response(200, json={"list": []})
    )
    response = forward_request("GET", "routes", "", None, {}, "application/json", "testuser")
    assert response.status_code == 200


@respx.mock
def test_forward_request_non_2xx_forwarded():
    respx.get("http://mock-apisix:9180/apisix/admin/routes").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    response = forward_request("GET", "routes", "", None, {}, "application/json", "testuser")
    assert response.status_code == 404


@respx.mock
def test_forward_request_connection_error_raises_503():
    respx.get("http://mock-apisix:9180/apisix/admin/routes").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(HTTPException) as exc:
        forward_request("GET", "routes", "", None, {}, "application/json", "testuser")
    assert exc.value.status_code == 503


def test_convert_body_if_yaml_converts():
    yaml_body = b"uri: /test\nname: my-route"
    result_body, result_ct = convert_body_if_yaml(yaml_body, "application/yaml")
    import json
    data = json.loads(result_body)
    assert data["uri"] == "/test"
    assert result_ct == "application/json"


def test_convert_body_if_json_passthrough():
    json_body = b'{"uri": "/test"}'
    result_body, result_ct = convert_body_if_yaml(json_body, "application/json")
    assert result_body == json_body
    assert result_ct == "application/json"


@respx.mock
def test_forward_request_timeout_raises_503():
    respx.get("http://mock-apisix:9180/apisix/admin/routes").mock(
        side_effect=httpx.TimeoutException("Request timed out")
    )
    with pytest.raises(HTTPException) as exc:
        forward_request("GET", "routes", "", None, {}, "application/json", "testuser")
    assert exc.value.status_code == 503
    assert "unreachable" in exc.value.detail.lower()


@respx.mock
def test_forward_request_produces_log_entry(caplog):
    """Test that every proxied request produces a log entry with required fields."""
    respx.get("http://mock-apisix:9180/apisix/admin/routes").mock(
        return_value=httpx.Response(200, json={"list": []})
    )
    with caplog.at_level(logging.INFO, logger="app.services.proxy_service"):
        forward_request("GET", "routes", "", None, {}, "application/json", "testuser")

    # Verify log entry contains required fields: PROXY, username, method, resource, status, duration
    assert len(caplog.records) >= 1
    log_message = caplog.records[-1].message
    assert "PROXY" in log_message
    assert "testuser" in log_message
    assert "GET" in log_message
    assert "routes" in log_message
    assert "200" in log_message
    assert "ms" in log_message


@respx.mock
def test_forward_request_log_entry_on_non_2xx(caplog):
    """Test that log entry is produced even for non-2xx responses."""
    respx.put("http://mock-apisix:9180/apisix/admin/services/123").mock(
        return_value=httpx.Response(409, json={"error": "conflict"})
    )
    with caplog.at_level(logging.INFO, logger="app.services.proxy_service"):
        forward_request("PUT", "services", "123", b'{"name":"svc"}', {}, "application/json", "admin")

    assert len(caplog.records) >= 1
    log_message = caplog.records[-1].message
    assert "PROXY" in log_message
    assert "admin" in log_message
    assert "PUT" in log_message
    assert "services" in log_message
    assert "409" in log_message
    assert "ms" in log_message


@respx.mock
def test_forward_request_with_sub_path():
    """Test that sub_path is correctly appended to the URL."""
    respx.get("http://mock-apisix:9180/apisix/admin/routes/12345").mock(
        return_value=httpx.Response(200, json={"id": "12345"})
    )
    response = forward_request("GET", "routes", "12345", None, {}, "application/json", "testuser")
    assert response.status_code == 200


@respx.mock
def test_forward_request_all_allowed_resources():
    """Test that all resources in the allowlist are forwarded successfully."""
    for resource in ALLOWED_RESOURCES:
        respx.route(method="GET", url=f"http://mock-apisix:9180/apisix/admin/{resource}").mock(
            return_value=httpx.Response(200, json={"list": []})
        )
        response = forward_request("GET", resource, "", None, {}, "application/json", "testuser")
        assert response.status_code == 200, f"Resource '{resource}' should be allowed"
