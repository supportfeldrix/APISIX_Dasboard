"""Shared pytest fixtures for the APISIX Dashboard test suite."""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from hypothesis import settings as h_settings

# Register Hypothesis profiles
h_settings.register_profile("ci", max_examples=100)
h_settings.register_profile("dev", max_examples=20)
h_settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))

# Set test environment variables before importing app modules
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-32chars")
os.environ.setdefault("APISIX_ADMIN_BASE_URL", "http://mock-apisix:9180")
os.environ.setdefault("APISIX_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("APISIX_METRICS_URL", "http://mock-metrics/metrics")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import Base, get_db
from app.models.user import User
from app.models.token_blacklist import TokenBlacklist


@pytest.fixture(scope="function")
def db_engine():
    """Create an in-memory SQLite engine for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Provide a database session for each test."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_user(db_session):
    """Create and return an admin user in the test database."""
    from app.services.auth_service import hash_password
    user = User(
        username="testadmin",
        hashed_password=hash_password("TestPass123!"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def viewer_user(db_session):
    """Create and return a viewer user in the test database."""
    from app.services.auth_service import hash_password
    user = User(
        username="testviewer",
        hashed_password=hash_password("ViewPass123!"),
        role="viewer",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
