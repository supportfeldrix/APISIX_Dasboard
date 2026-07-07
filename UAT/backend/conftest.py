"""Shared test fixtures and Hypothesis profile configuration."""
import os

# ---------------------------------------------------------------------------
# Set required environment variables BEFORE importing app modules
# ---------------------------------------------------------------------------
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("APISIX_ADMIN_BASE_URL", "http://mock-apisix:9180")
os.environ.setdefault("APISIX_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("APISIX_METRICS_URL", "http://localhost:9091/metrics")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
import respx
import httpx
from hypothesis import settings as h_settings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings as app_settings
from app.database import Base, get_db
from app.models.user import User
from app.models.token_blacklist import TokenBlacklist  # noqa: F401 — ensure table registered
from app.services.auth_service import hash_password, create_access_token
from app.main import app


# ---------------------------------------------------------------------------
# Hypothesis profile configuration
# ---------------------------------------------------------------------------

h_settings.register_profile("ci", max_examples=100)
h_settings.register_profile("dev", max_examples=20)
h_settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))


# ---------------------------------------------------------------------------
# Test database setup — in-memory SQLite with StaticPool
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_engine():
    """Create a fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture()
def db_session(test_engine):
    """Provide a database session that rolls back after each test."""
    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(test_engine):
    """Return a FastAPI TestClient with the database dependency overridden."""
    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    # Seed test users
    db = TestSessionLocal()
    db.add(User(
        username="test_viewer",
        hashed_password=hash_password("ViewerPass1!"),
        role="viewer",
        is_active=True,
    ))
    db.add(User(
        username="test_admin",
        hashed_password=hash_password("AdminPass1!"),
        role="admin",
        is_active=True,
    ))
    db.commit()
    db.close()

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Mock APISIX Admin API client fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_apisix():
    """Mock the APISIX Admin API base URL using respx.

    Usage:
        def test_something(client, mock_apisix):
            mock_apisix.get("/apisix/admin/routes").mock(
                return_value=httpx.Response(200, json={"list": []})
            )
            ...
    """
    base_url = app_settings.APISIX_ADMIN_BASE_URL
    with respx.mock(base_url=base_url) as respx_mock:
        yield respx_mock


# ---------------------------------------------------------------------------
# Auth helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def viewer_token():
    """Generate a valid JWT token for the test viewer user."""
    return create_access_token({"sub": "test_viewer", "role": "viewer"})


@pytest.fixture()
def admin_token():
    """Generate a valid JWT token for the test admin user."""
    return create_access_token({"sub": "test_admin", "role": "admin"})
