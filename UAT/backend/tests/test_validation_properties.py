"""Property-based tests for payload validation.

Tests that invalid payloads always raise ValidationError with field-level errors
when validated against the Pydantic schemas.
"""
import pytest
from hypothesis import given, settings as h_settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.apisix import (
    RoutePayload,
    ServicePayload,
    UpstreamPayload,
    ConsumerPayload,
    SSLPayload,
)


# ---------------------------------------------------------------------------
# Strategies for generating invalid payloads
# ---------------------------------------------------------------------------

# Types that are never valid for string fields
non_string_values = st.one_of(
    st.integers(),
    st.floats(allow_nan=False),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
    st.booleans(),
)

# Types that are never valid for list fields
non_list_values = st.one_of(
    st.integers(),
    st.floats(allow_nan=False),
    st.text(min_size=1, max_size=20),
    st.booleans(),
)

# Types that are never valid for dict fields
non_dict_values = st.one_of(
    st.integers(),
    st.floats(allow_nan=False),
    st.text(min_size=1, max_size=20),
    st.booleans(),
    st.lists(st.integers(), max_size=3),
)


# Strategy: RoutePayload missing required 'uri' field
invalid_route_missing_uri = st.fixed_dictionaries({
    "name": st.one_of(st.none(), st.text(max_size=20)),
    "methods": st.one_of(st.none(), st.lists(st.text(max_size=10), max_size=3)),
})

# Strategy: RoutePayload with wrong type for 'uri'
invalid_route_wrong_uri_type = st.fixed_dictionaries({
    "uri": non_string_values,
    "name": st.one_of(st.none(), st.text(max_size=20)),
})

# Strategy: ConsumerPayload missing required 'username' field
invalid_consumer_missing_username = st.fixed_dictionaries({
    "plugins": st.one_of(st.none(), st.dictionaries(st.text(max_size=10), st.integers(), max_size=2)),
})

# Strategy: ConsumerPayload with wrong type for 'username'
invalid_consumer_wrong_username_type = st.fixed_dictionaries({
    "username": non_string_values,
})

# Strategy: SSLPayload missing required fields
invalid_ssl_missing_fields = st.one_of(
    # Missing both cert and key
    st.fixed_dictionaries({
        "snis": st.one_of(st.none(), st.lists(st.text(max_size=20), max_size=2)),
    }),
    # Missing key
    st.fixed_dictionaries({
        "cert": st.text(min_size=1, max_size=50),
    }),
    # Missing cert
    st.fixed_dictionaries({
        "key": st.text(min_size=1, max_size=50),
    }),
)

# Strategy: SSLPayload with wrong types
invalid_ssl_wrong_types = st.fixed_dictionaries({
    "cert": non_string_values,
    "key": non_string_values,
})

# Strategy: RoutePayload with wrong type for 'methods' (should be list of strings)
invalid_route_wrong_methods_type = st.fixed_dictionaries({
    "uri": st.text(min_size=1, max_size=30),
    "methods": non_list_values,
})

# Strategy: RoutePayload with wrong type for 'plugins' (should be dict)
invalid_route_wrong_plugins_type = st.fixed_dictionaries({
    "uri": st.text(min_size=1, max_size=30),
    "plugins": non_dict_values,
})

# Combined strategy for all invalid payloads
invalid_payload_strategy = st.one_of(
    # RoutePayload invalids
    st.tuples(st.just("route_missing_uri"), invalid_route_missing_uri),
    st.tuples(st.just("route_wrong_uri_type"), invalid_route_wrong_uri_type),
    st.tuples(st.just("route_wrong_methods_type"), invalid_route_wrong_methods_type),
    st.tuples(st.just("route_wrong_plugins_type"), invalid_route_wrong_plugins_type),
    # ConsumerPayload invalids
    st.tuples(st.just("consumer_missing_username"), invalid_consumer_missing_username),
    st.tuples(st.just("consumer_wrong_username_type"), invalid_consumer_wrong_username_type),
    # SSLPayload invalids
    st.tuples(st.just("ssl_missing_fields"), invalid_ssl_missing_fields),
    st.tuples(st.just("ssl_wrong_types"), invalid_ssl_wrong_types),
)


# ---------------------------------------------------------------------------
# Property 8: Invalid payloads always return 422 with field-level errors
# Feature: apisix-dashboard, Property 8: Invalid payloads always return 422 with field-level errors
# ---------------------------------------------------------------------------

@given(scenario=invalid_payload_strategy)
@h_settings(max_examples=25)
def test_property_8_invalid_payloads_raise_validation_error(scenario):
    """Property 8: Invalid payloads always raise ValidationError with field-level errors.

    This validates that structurally invalid payloads (missing required fields,
    wrong data types) are always rejected by Pydantic with specific field errors.
    """
    error_type, payload = scenario

    if error_type.startswith("route_"):
        model_class = RoutePayload
    elif error_type.startswith("consumer_"):
        model_class = ConsumerPayload
    elif error_type.startswith("ssl_"):
        model_class = SSLPayload
    else:
        pytest.fail(f"Unknown error type: {error_type}")

    with pytest.raises(ValidationError) as exc_info:
        model_class(**payload)

    # Verify field-level errors are present
    errors = exc_info.value.errors()
    assert len(errors) >= 1, "ValidationError should contain at least one field error"

    # Each error must have a location (field path) and a type
    for error in errors:
        assert "loc" in error, "Each error must specify the field location"
        assert "type" in error, "Each error must specify the error type"
        assert len(error["loc"]) >= 1, "Field location must not be empty"


@given(
    uri_value=non_string_values,
)
@h_settings(max_examples=25)
def test_property_8_route_uri_type_validation(uri_value):
    """Property 8 (Route): Non-string uri values always produce a validation error."""
    # Filter out values that Pydantic might coerce to string
    assume(not isinstance(uri_value, (bool,)))

    with pytest.raises(ValidationError) as exc_info:
        RoutePayload(uri=uri_value)

    errors = exc_info.value.errors()
    assert len(errors) >= 1
    # At least one error should reference the 'uri' field
    field_names = [e["loc"][0] for e in errors if e["loc"]]
    assert "uri" in field_names, f"Expected 'uri' in error fields, got {field_names}"


@given(
    username_value=non_string_values,
)
@h_settings(max_examples=25)
def test_property_8_consumer_username_type_validation(username_value):
    """Property 8 (Consumer): Non-string username values always produce a validation error."""
    assume(not isinstance(username_value, (bool,)))

    with pytest.raises(ValidationError) as exc_info:
        ConsumerPayload(username=username_value)

    errors = exc_info.value.errors()
    assert len(errors) >= 1
    field_names = [e["loc"][0] for e in errors if e["loc"]]
    assert "username" in field_names, f"Expected 'username' in error fields, got {field_names}"


@given(
    cert_value=non_string_values,
    key_value=non_string_values,
)
@h_settings(max_examples=25)
def test_property_8_ssl_type_validation(cert_value, key_value):
    """Property 8 (SSL): Non-string cert/key values always produce validation errors."""
    assume(not isinstance(cert_value, (bool,)))
    assume(not isinstance(key_value, (bool,)))

    with pytest.raises(ValidationError) as exc_info:
        SSLPayload(cert=cert_value, key=key_value)

    errors = exc_info.value.errors()
    assert len(errors) >= 1
    field_names = [e["loc"][0] for e in errors if e["loc"]]
    assert "cert" in field_names or "key" in field_names, (
        f"Expected 'cert' or 'key' in error fields, got {field_names}"
    )


def test_property_8_route_missing_required_uri():
    """Property 8: RoutePayload without 'uri' always raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        RoutePayload(name="test-route")

    errors = exc_info.value.errors()
    assert len(errors) >= 1
    field_names = [e["loc"][0] for e in errors]
    assert "uri" in field_names


def test_property_8_consumer_missing_required_username():
    """Property 8: ConsumerPayload without 'username' always raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ConsumerPayload(plugins={"key-auth": {}})

    errors = exc_info.value.errors()
    assert len(errors) >= 1
    field_names = [e["loc"][0] for e in errors]
    assert "username" in field_names


def test_property_8_ssl_missing_required_cert_and_key():
    """Property 8: SSLPayload without 'cert' and 'key' always raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        SSLPayload(snis=["example.com"])

    errors = exc_info.value.errors()
    assert len(errors) >= 1
    field_names = [e["loc"][0] for e in errors]
    assert "cert" in field_names or "key" in field_names
