"""Application configuration loaded from environment variables."""
import logging
import re
from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # --- Authentication ---
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 30

    # --- APISIX Admin API ---
    APISIX_ADMIN_BASE_URL: str
    APISIX_ADMIN_KEY: str
    APISIX_ADMIN_VERIFY_SSL: bool = True
    APISIX_ADMIN_TIMEOUT: int = 10

    # --- Prometheus Metrics ---
    APISIX_METRICS_URL: str
    APISIX_METRICS_TIMEOUT: int = 10

    # --- OpenShift / Kubernetes API ---
    OC_API_SERVER: str = ""
    OC_TOKEN: str = ""
    OC_NAMESPACE: str = "cro-apisix-uat"
    OC_VERIFY_SSL: bool = False

    # --- LDAP ---
    LDAP_ENABLED: bool = True
    LDAP_SERVER: str = "ldaps://ldap.fnbconnect.co.za:636"
    LDAP_BASE_DN: str = "DC=fnb,DC=co,DC=za"
    LDAP_USER_FILTER: str = "(&(objectClass=user)(sAMAccountName={username}))"
    LDAP_BIND_DN: str = "SVC_cro_ansible_dev@fnb.co.za"
    LDAP_BIND_PASSWORD: str = ""
    LDAP_GROUP_BASE_DN: str = "OU=GlobalSecurityGroups,OU=DomainGroups,DC=fnb,DC=co,DC=za"
    LDAP_ADMIN_GROUP: str = ""
    LDAP_USE_SSL: bool = True
    LDAP_VERIFY_SSL: bool = False

    # --- SMTP (Email Notifications) ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_ADDRESS: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_VERIFY_SSL: bool = True

    # --- Notification Scheduler ---
    NOTIFICATION_EVAL_INTERVAL: int = 60  # seconds between evaluation cycles (10-3600)
    NOTIFICATION_LOG_RETENTION_DAYS: int = 90  # days to retain notification logs

    # --- Version Check ---
    GITHUB_API_TIMEOUT: int = 10
    GITHUB_PROXY_URL: str = ""
    VERSION_CHECK_INTERVAL_HOURS: int = 24

    @field_validator("GITHUB_API_TIMEOUT", mode="before")
    @classmethod
    def _validate_github_api_timeout(cls, v: object) -> int:
        try:
            val = int(v)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid GITHUB_API_TIMEOUT value '%s'; falling back to default 10",
                v,
            )
            return 10
        if val < 1 or val > 120:
            logger.warning(
                "GITHUB_API_TIMEOUT=%d is outside valid range [1, 120]; falling back to default 10",
                val,
            )
            return 10
        return val

    @field_validator("GITHUB_PROXY_URL", mode="before")
    @classmethod
    def _validate_github_proxy_url(cls, v: object) -> str:
        if v is None:
            return ""
        val = str(v).strip()
        if val == "":
            return ""
        if not re.match(r"^https?://", val, re.IGNORECASE):
            logger.warning(
                "GITHUB_PROXY_URL='%s' is not a valid http(s):// URL; falling back to default ''",
                val,
            )
            return ""
        return val

    @field_validator("VERSION_CHECK_INTERVAL_HOURS", mode="before")
    @classmethod
    def _validate_version_check_interval_hours(cls, v: object) -> int:
        try:
            val = int(v)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid VERSION_CHECK_INTERVAL_HOURS value '%s'; falling back to default 24",
                v,
            )
            return 24
        if val < 1 or val > 168:
            logger.warning(
                "VERSION_CHECK_INTERVAL_HOURS=%d is outside valid range [1, 168]; falling back to default 24",
                val,
            )
            return 24
        return val

    # --- Database ---
    DATABASE_URL: str = "sqlite:///./apisix_dashboard.db"

    # --- Server ---
    CORS_ORIGINS: str = "http://localhost:5173"
    ROOT_PATH: str = ""
    LOG_LEVEL: str = "INFO"

    # --- Application Environment ---
    APP_ENVIRONMENT: str = "DEV"

    def get_cors_origins(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()


# Singleton instance for direct import
settings = get_settings()
