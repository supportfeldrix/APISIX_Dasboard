"""Unit tests for the SSL upload router."""
import io
import pytest
import respx
import httpx
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.services.auth_service import get_current_user
from app.models.user import User


# --- Fixtures ---

@pytest.fixture
def mock_user():
    """Return a mock admin user."""
    user = User(username="testadmin", role="admin", is_active=True)
    user.id = 1
    return user


@pytest.fixture
def client(mock_user, db_session):
    """Create a test client with overridden dependencies."""
    def override_get_current_user():
        return mock_user

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- Valid PEM content for testing ---

VALID_CERT = """-----BEGIN CERTIFICATE-----
MIIBkTCB+wIJALRiMLAhKwEHMA0GCSqGSIb3DQEBCwUAMBExDzANBgNVBAMMBnRl
c3RjYTAeFw0yMzAxMDEwMDAwMDBaFw0yNDAxMDEwMDAwMDBaMBExDzANBgNVBAMM
BnRlc3RjYTBcMA0GCSqGSIb3DQEBAQUAAwsAMEgCQQC7o96h+ZhZz7eE1xk/sDfH
-----END CERTIFICATE-----"""

VALID_KEY = """-----BEGIN PRIVATE KEY-----
MIIBVAIBADANBgkqhkiG9w0BAQEFAASCAT4wggE6AgEAAkEAu6PeofmYWc+3hNcZ
P7A3x0123456789abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMN
-----END PRIVATE KEY-----"""


# --- Tests ---

def test_upload_no_files_returns_422(client):
    """Test that uploading with no files returns 422."""
    response = client.post("/api/ssl/upload", data={"snis": "example.com"})
    assert response.status_code == 422
    assert "At least one file" in response.json()["detail"]


def test_upload_invalid_extension_returns_422(client):
    """Test that uploading a file with invalid extension returns 422."""
    files = {"cert_file": ("cert.txt", io.BytesIO(VALID_CERT.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    assert response.status_code == 422
    assert "extension not allowed" in response.json()["detail"]


def test_upload_oversized_file_returns_413(client):
    """Test that uploading a file > 1 MB returns 413."""
    large_content = b"x" * (1_048_576 + 1)
    files = {"cert_file": ("cert.pem", io.BytesIO(large_content), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    assert response.status_code == 413
    assert "exceeds maximum" in response.json()["detail"]


def test_upload_non_utf8_returns_422(client):
    """Test that uploading a non-UTF-8 file returns 422."""
    binary_content = bytes([0xFF, 0xFE, 0x00, 0x01] * 100)
    files = {"cert_file": ("cert.pem", io.BytesIO(binary_content), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    assert response.status_code == 422
    assert "not valid UTF-8" in response.json()["detail"]


def test_upload_invalid_pem_cert_returns_422(client):
    """Test that uploading an invalid PEM certificate returns 422."""
    invalid_cert = "This is not a valid PEM certificate"
    files = {"cert_file": ("cert.pem", io.BytesIO(invalid_cert.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    assert response.status_code == 422
    assert "Invalid PEM certificate format" in response.json()["detail"]


def test_upload_invalid_pem_key_returns_422(client):
    """Test that uploading an invalid PEM key returns 422."""
    invalid_key = "This is not a valid PEM key"
    files = {"key_file": ("key.key", io.BytesIO(invalid_key.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    assert response.status_code == 422
    assert "Invalid PEM private key format" in response.json()["detail"]


@respx.mock
def test_upload_valid_cert_forwards_to_apisix(client):
    """Test that a valid cert file is forwarded to APISIX."""
    respx.post("http://mock-apisix:9180/apisix/admin/ssl").mock(
        return_value=httpx.Response(201, json={"key": "/apisix/ssls/1", "value": {"id": "1"}})
    )
    files = {"cert_file": ("cert.pem", io.BytesIO(VALID_CERT.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": "example.com"})
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert data["apisix_response"] is not None


@respx.mock
def test_upload_valid_cert_and_key_forwards_to_apisix(client):
    """Test that valid cert and key files are forwarded to APISIX."""
    respx.post("http://mock-apisix:9180/apisix/admin/ssl").mock(
        return_value=httpx.Response(201, json={"key": "/apisix/ssls/1", "value": {"id": "1"}})
    )
    files = {
        "cert_file": ("cert.crt", io.BytesIO(VALID_CERT.encode()), "application/octet-stream"),
        "key_file": ("key.key", io.BytesIO(VALID_KEY.encode()), "application/octet-stream"),
    }
    response = client.post("/api/ssl/upload", files=files, data={"snis": "example.com, *.example.com"})
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"


@respx.mock
def test_upload_apisix_error_forwarded(client):
    """Test that APISIX error responses are forwarded to the client."""
    respx.post("http://mock-apisix:9180/apisix/admin/ssl").mock(
        return_value=httpx.Response(400, json={"error_msg": "invalid certificate"})
    )
    files = {"cert_file": ("cert.pem", io.BytesIO(VALID_CERT.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    assert response.status_code == 400


@respx.mock
def test_upload_apisix_unreachable_returns_503(client):
    """Test that APISIX unreachable returns 503."""
    respx.post("http://mock-apisix:9180/apisix/admin/ssl").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    files = {"cert_file": ("cert.pem", io.BytesIO(VALID_CERT.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"].lower()


def test_upload_file_at_exactly_1mb_accepted(client):
    """Test that a file exactly at 1 MB is accepted (not rejected)."""
    # Create valid PEM content padded to exactly 1 MB
    cert_header = "-----BEGIN CERTIFICATE-----\n"
    cert_footer = "\n-----END CERTIFICATE-----"
    padding_size = 1_048_576 - len(cert_header) - len(cert_footer)
    # Use base64-like characters for padding
    padding = "A" * padding_size
    content = cert_header + padding + cert_footer

    files = {"cert_file": ("cert.pem", io.BytesIO(content.encode()), "application/octet-stream")}
    # This should pass size validation but may fail PEM validation (that's fine for this test)
    # We're testing size boundary, not PEM validity
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    # Should NOT be 413 (file size is exactly 1 MB)
    assert response.status_code != 413


def test_upload_case_insensitive_extension(client):
    """Test that file extensions are validated case-insensitively."""
    files = {"cert_file": ("cert.PEM", io.BytesIO(VALID_CERT.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": ""})
    # Should NOT be rejected for extension (may pass or fail on PEM validation)
    assert response.status_code != 422 or "extension" not in response.json().get("detail", "")


@respx.mock
def test_upload_snis_parsed_correctly(client):
    """Test that snis string is parsed into an array."""
    route = respx.post("http://mock-apisix:9180/apisix/admin/ssl").mock(
        return_value=httpx.Response(201, json={"key": "/apisix/ssls/1"})
    )
    files = {"cert_file": ("cert.pem", io.BytesIO(VALID_CERT.encode()), "application/octet-stream")}
    response = client.post("/api/ssl/upload", files=files, data={"snis": "a.com, b.com, c.com"})
    assert response.status_code == 201

    # Verify the request body sent to APISIX contains snis as array
    import json
    request_body = json.loads(route.calls[0].request.content)
    assert request_body["snis"] == ["a.com", "b.com", "c.com"]
