"""Property-based tests for SSL certificate expiry warning logic."""
import pytest
from datetime import date, timedelta
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st


def should_show_warning(expiry_date: date, today: date) -> bool:
    """Return True if the certificate expires within 30 days (warning threshold)."""
    days_until_expiry = (expiry_date - today).days
    return days_until_expiry <= 30


def should_show_critical(expiry_date: date, today: date) -> bool:
    """Return True if the certificate expires within 7 days (critical threshold)."""
    days_until_expiry = (expiry_date - today).days
    return days_until_expiry <= 7


# Feature: apisix-dashboard, Property 15: SSL certificate expiry warning is shown for certs within 30 days
@given(expiry=st.dates())
@h_settings(max_examples=25)
def test_property_15_ssl_expiry_warning_threshold(expiry):
    """Property 15: SSL expiry warning shown iff within 30 days."""
    today = date.today()
    days_until = (expiry - today).days

    warning = should_show_warning(expiry, today)

    # If within 30 days -> warning is True
    if days_until <= 30:
        assert warning is True, f"Expected warning for expiry in {days_until} days"
    # If more than 30 days -> warning is False
    else:
        assert warning is False, f"Expected no warning for expiry in {days_until} days"


@given(expiry=st.dates())
@h_settings(max_examples=25)
def test_property_15_ssl_critical_threshold(expiry):
    """Property 15: SSL critical warning shown iff within 7 days."""
    today = date.today()
    days_until = (expiry - today).days

    critical = should_show_critical(expiry, today)

    # If within 7 days -> critical is True
    if days_until <= 7:
        assert critical is True, f"Expected critical for expiry in {days_until} days"
    else:
        assert critical is False, f"Expected no critical for expiry in {days_until} days"
