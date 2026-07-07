"""Property-based tests for YAML <-> JSON converter."""
import json

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from app.utils.yaml_converter import yaml_to_json, json_to_yaml


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy: valid YAML-safe values (no NaN/Inf which don't round-trip cleanly)
_yaml_safe_scalars = st.one_of(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters=" ",
        ),
        min_size=1,
        max_size=15,
    ),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(
        min_value=-1e6,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
    st.booleans(),
)

# Recursive strategy for YAML-safe documents (dicts/lists with simple values)
yaml_document_strategy = st.recursive(
    _yaml_safe_scalars,
    lambda children: st.one_of(
        st.lists(children, min_size=1, max_size=4),
        st.dictionaries(
            st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
                min_size=1,
                max_size=8,
            ),
            children,
            min_size=1,
            max_size=4,
        ),
    ),
    max_leaves=15,
)

# Recursive strategy for JSON-serializable documents
_json_safe_scalars = st.one_of(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters=" ",
        ),
        min_size=1,
        max_size=15,
    ),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(
        min_value=-1e6,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
    st.booleans(),
)

json_document_strategy = st.recursive(
    _json_safe_scalars,
    lambda children: st.one_of(
        st.lists(children, min_size=1, max_size=4),
        st.dictionaries(
            st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
                min_size=1,
                max_size=8,
            ),
            children,
            min_size=1,
            max_size=4,
        ),
    ),
    max_leaves=15,
)

# Strategy for syntactically invalid YAML strings
invalid_yaml_strategy = st.sampled_from([
    "{key: [}",
    "key: [unclosed",
    ":\n\t- mixed\n  - indentation",
    "{{{{",
    "key: {nested: [}",
    "- item1\n\t- tab_indented\n  - space_indented",
    "key: value\n  bad_indent: yes\n bad_indent2: no",
    "*undefined_alias",
    "---\n...\n---\n{: broken}",
    "{unbalanced: {",
    "[\n  - mixing flow and block",
    "key: &anchor\n  <<: *missing",
    "!!invalid/tag value",
    "{key: value,, extra_comma}",
    "{\n  key: ]mismatched",
])


# ---------------------------------------------------------------------------
# Property 12a: YAML -> JSON -> YAML round-trip is lossless
# ---------------------------------------------------------------------------

# Feature: apisix-dashboard, Property 12: YAML↔JSON conversion is lossless (round-trip)
@given(data=yaml_document_strategy)
@settings(max_examples=25)
def test_property_12a_yaml_to_json_to_yaml_roundtrip(data):
    """YAML→JSON→YAML round-trip preserves data."""
    # Convert Python dict/list to YAML string
    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True)

    # Round-trip: YAML → JSON → YAML
    json_str = yaml_to_json(yaml_str)
    yaml_back = json_to_yaml(json_str)

    # Parse the final YAML and compare to original
    result = yaml.safe_load(yaml_back)
    assert result == data


# ---------------------------------------------------------------------------
# Property 12b: JSON -> YAML -> JSON round-trip is lossless
# ---------------------------------------------------------------------------

# Feature: apisix-dashboard, Property 12: YAML↔JSON conversion is lossless (round-trip)
@given(data=json_document_strategy)
@settings(max_examples=25)
def test_property_12b_json_to_yaml_to_json_roundtrip(data):
    """JSON→YAML→JSON round-trip preserves data."""
    # Convert Python dict/list to JSON string
    json_str = json.dumps(data)

    # Round-trip: JSON → YAML → JSON
    yaml_str = json_to_yaml(json_str)
    json_back = yaml_to_json(yaml_str)

    # Parse the final JSON and compare to original
    result = json.loads(json_back)
    assert result == data


# ---------------------------------------------------------------------------
# Property 13: Invalid YAML always raises ValueError
# ---------------------------------------------------------------------------

# Feature: apisix-dashboard, Property 13: Syntactically invalid YAML/JSON is always rejected before submission
@given(text=invalid_yaml_strategy)
@settings(max_examples=25)
def test_property_13_invalid_yaml_raises_value_error(text):
    """Syntactically invalid YAML always raises ValueError."""
    with pytest.raises(ValueError):
        yaml_to_json(text)
