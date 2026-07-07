"""Pydantic schemas for email notification alert rules and logs."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


# --- Enums ---

class ConditionType(str, Enum):
    """Supported failure condition types for alert rules."""
    JWT_FAILURE = "JWT_FAILURE"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    CLIENT_ERROR = "CLIENT_ERROR"
    HIGH_ERROR_RATE = "HIGH_ERROR_RATE"
    HEALTH_CHECK_FAILURE = "HEALTH_CHECK_FAILURE"
    POD_HEALTH = "POD_HEALTH"


class DeliveryStatus(str, Enum):
    """Delivery status for notification log entries."""
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


# --- Constants ---

NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

# Condition types that use percentage-based thresholds (1-100)
PERCENTAGE_CONDITIONS = {ConditionType.HIGH_ERROR_RATE}
# Condition types that use count-based thresholds (1-10000)
COUNT_CONDITIONS = {
    ConditionType.JWT_FAILURE,
    ConditionType.UPSTREAM_ERROR,
    ConditionType.CLIENT_ERROR,
    ConditionType.HEALTH_CHECK_FAILURE,
    ConditionType.POD_HEALTH,
}


# --- Alert Rule Schemas ---

class AlertRuleCreate(BaseModel):
    """Schema for creating a new alert rule."""
    name: str
    route_id: str
    condition_type: ConditionType
    threshold: int
    recipients: list[str]
    cooldown_seconds: int
    enabled: bool = True
    health_check_url: Optional[str] = None
    health_check_interval: Optional[int] = 60
    health_check_failures_threshold: Optional[int] = 3
    notify_controlm: bool = False
    critical: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v) < 1 or len(v) > 128:
            raise ValueError("Name must be between 1 and 128 characters")
        if not NAME_PATTERN.match(v):
            raise ValueError(
                "Name must contain only alphanumeric characters, hyphens, and underscores"
            )
        return v

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: list[str]) -> list[str]:
        if len(v) < 1:
            raise ValueError("At least 1 recipient email address is required")
        if len(v) > 10:
            raise ValueError("Maximum 10 recipient email addresses allowed")
        for email in v:
            if not EMAIL_PATTERN.match(email):
                raise ValueError(f"Invalid email address: {email}")
        return v

    @field_validator("cooldown_seconds")
    @classmethod
    def validate_cooldown(cls, v: int) -> int:
        if v < 60 or v > 86400:
            raise ValueError("Cooldown must be between 60 and 86400 seconds")
        return v

    @field_validator("health_check_interval")
    @classmethod
    def validate_health_check_interval(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 10 or v > 3600):
            raise ValueError("Health check interval must be between 10 and 3600 seconds")
        return v

    @field_validator("health_check_failures_threshold")
    @classmethod
    def validate_health_check_failures_threshold(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 10):
            raise ValueError(
                "Health check failures threshold must be between 1 and 10"
            )
        return v

    @model_validator(mode="after")
    def validate_threshold_range(self) -> "AlertRuleCreate":
        """Validate threshold based on condition type."""
        if self.condition_type in PERCENTAGE_CONDITIONS:
            if self.threshold < 1 or self.threshold > 100:
                raise ValueError(
                    "Threshold must be between 1 and 100 for percentage-based conditions"
                )
        else:
            if self.threshold < 1 or self.threshold > 10000:
                raise ValueError(
                    "Threshold must be between 1 and 10000 for count-based conditions"
                )
        return self


class AlertRuleUpdate(BaseModel):
    """Schema for updating an existing alert rule. All fields optional."""
    name: Optional[str] = None
    route_id: Optional[str] = None
    condition_type: Optional[ConditionType] = None
    threshold: Optional[int] = None
    recipients: Optional[list[str]] = None
    cooldown_seconds: Optional[int] = None
    enabled: Optional[bool] = None
    health_check_url: Optional[str] = None
    health_check_interval: Optional[int] = None
    health_check_failures_threshold: Optional[int] = None
    notify_controlm: Optional[bool] = None
    critical: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v or len(v) < 1 or len(v) > 128:
            raise ValueError("Name must be between 1 and 128 characters")
        if not NAME_PATTERN.match(v):
            raise ValueError(
                "Name must contain only alphanumeric characters, hyphens, and underscores"
            )
        return v

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        if len(v) < 1:
            raise ValueError("At least 1 recipient email address is required")
        if len(v) > 10:
            raise ValueError("Maximum 10 recipient email addresses allowed")
        for email in v:
            if not EMAIL_PATTERN.match(email):
                raise ValueError(f"Invalid email address: {email}")
        return v

    @field_validator("cooldown_seconds")
    @classmethod
    def validate_cooldown(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 60 or v > 86400:
            raise ValueError("Cooldown must be between 60 and 86400 seconds")
        return v

    @field_validator("health_check_interval")
    @classmethod
    def validate_health_check_interval(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 10 or v > 3600):
            raise ValueError("Health check interval must be between 10 and 3600 seconds")
        return v

    @field_validator("health_check_failures_threshold")
    @classmethod
    def validate_health_check_failures_threshold(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 10):
            raise ValueError(
                "Health check failures threshold must be between 1 and 10"
            )
        return v

    @model_validator(mode="after")
    def validate_threshold_range(self) -> "AlertRuleUpdate":
        """Validate threshold based on condition type when both are provided."""
        if self.threshold is not None and self.condition_type is not None:
            if self.condition_type in PERCENTAGE_CONDITIONS:
                if self.threshold < 1 or self.threshold > 100:
                    raise ValueError(
                        "Threshold must be between 1 and 100 for percentage-based conditions"
                    )
            else:
                if self.threshold < 1 or self.threshold > 10000:
                    raise ValueError(
                        "Threshold must be between 1 and 10000 for count-based conditions"
                    )
        return self


class AlertRuleResponse(BaseModel):
    """Schema for alert rule API responses."""
    id: int
    name: str
    route_id: str
    route_name: Optional[str] = None
    condition_type: ConditionType
    threshold: int
    recipients: list[str]
    cooldown_seconds: int
    enabled: bool
    health_check_url: Optional[str] = None
    health_check_interval: Optional[int] = None
    health_check_failures_threshold: Optional[int] = None
    notify_controlm: bool
    critical: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Notification Log Schemas ---

class NotificationLogResponse(BaseModel):
    """Schema for notification log API responses."""
    id: int
    timestamp: datetime
    alert_rule_id: Optional[int] = None
    route_id: str
    route_name: Optional[str] = None
    condition_type: str
    recipients: list[str]
    subject: str
    delivery_status: str
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class PaginatedLogs(BaseModel):
    """Paginated response for notification log queries."""
    items: list[NotificationLogResponse]
    total: int
    page: int
    page_size: int


class LogFilters(BaseModel):
    """Query filters for notification log endpoint."""
    route_id: Optional[str] = None
    condition_type: Optional[ConditionType] = None
    delivery_status: Optional[DeliveryStatus] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    page: int = 1
    page_size: int = 25

    @field_validator("page")
    @classmethod
    def validate_page(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Page must be at least 1")
        return v

    @field_validator("page_size")
    @classmethod
    def validate_page_size(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("Page size must be between 1 and 100")
        return v


# --- Internal Data Classes ---

@dataclass
class AlertContext:
    """Context passed from evaluator to dispatcher when an alert triggers."""
    rule_id: int
    rule_name: str
    route_id: str
    route_name: str
    condition_type: str
    metric_values: dict = field(default_factory=dict)
    threshold: int = 0
    evaluation_window_start: Optional[datetime] = None
    evaluation_window_end: Optional[datetime] = None
    is_recovery: bool = False


@dataclass
class DeliveryResult:
    """Result of an email delivery attempt."""
    success: bool
    error_message: Optional[str] = None
    attempts: int = 1
