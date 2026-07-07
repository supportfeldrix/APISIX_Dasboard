"""Property-based preservation tests for evaluate_upstream_error.

These tests lock in the correct baseline behavior of the UNFIXED code for
non-buggy inputs — i.e., inputs that do NOT trigger the bug condition.

The function must return None when:
- Route metrics contain only 2xx/3xx/4xx status codes (no 5xx)
- Total 5xx count is below the configured threshold
- Route ID is not present in route_metrics
- Route has zero total traffic

These tests are written and verified BEFORE implementing the fix to ensure
the fix does not introduce regressions in the existing correct behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
"""
import os
import sys

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Ensure app modules can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.metrics_evaluator import evaluate_upstream_error


# --- Strategies ---

# Status codes that are NOT 5xx (200-499 only)
non_5xx_codes = st.integers(min_value=200, max_value=499)

# All possible 5xx codes (500-599)
all_5xx_codes = st.integers(min_value=500, max_value=599)

# Positive request counts
positive_counts = st.integers(min_value=1, max_value=10000)

# Thresholds (minimum 1 to be meaningful)
thresholds = st.integers(min_value=1, max_value=10000)

# Route IDs
route_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)


def build_route_metrics_dict(route_id: str, code_count_pairs: list) -> dict:
    """Build route_metrics dict in the format expected by evaluate_upstream_error."""
    metrics = {}
    for code, count in code_count_pairs:
        code_str = str(code)
        metrics[code_str] = metrics.get(code_str, 0) + count
    return {route_id: metrics}


# --- Strategy: non-5xx route metrics ---

@st.composite
def non_5xx_route_metrics(draw):
    """Generate route_metrics containing only 2xx/3xx/4xx codes (no 5xx)."""
    route_id = draw(route_ids)
    num_codes = draw(st.integers(min_value=1, max_value=10))
    code_count_pairs = draw(
        st.lists(
            st.tuples(non_5xx_codes, positive_counts),
            min_size=num_codes,
            max_size=num_codes,
        )
    )
    route_metrics = build_route_metrics_dict(route_id, code_count_pairs)
    return route_metrics, route_id


@st.composite
def below_threshold_5xx_metrics(draw):
    """Generate route_metrics where total 5xx count is strictly below the threshold."""
    route_id = draw(route_ids)

    # Generate some non-5xx codes for background traffic
    num_non_5xx = draw(st.integers(min_value=1, max_value=5))
    non_5xx_pairs = draw(
        st.lists(
            st.tuples(non_5xx_codes, positive_counts),
            min_size=num_non_5xx,
            max_size=num_non_5xx,
        )
    )

    # Generate 5xx codes with counts that sum below threshold
    num_5xx = draw(st.integers(min_value=1, max_value=5))
    five_xx_codes = draw(
        st.lists(all_5xx_codes, min_size=num_5xx, max_size=num_5xx)
    )
    # Each 5xx code gets a small count
    five_xx_counts = draw(
        st.lists(
            st.integers(min_value=1, max_value=10),
            min_size=num_5xx,
            max_size=num_5xx,
        )
    )
    five_xx_pairs = list(zip(five_xx_codes, five_xx_counts))

    # Calculate total 5xx sum
    total_5xx = sum(c for _, c in five_xx_pairs)

    # Threshold must be strictly greater than total 5xx sum
    threshold = draw(st.integers(min_value=total_5xx + 1, max_value=total_5xx + 1000))

    all_pairs = non_5xx_pairs + five_xx_pairs
    route_metrics = build_route_metrics_dict(route_id, all_pairs)
    return route_metrics, route_id, threshold


# --- Property Tests ---


class TestPreservationPropertyA:
    """Property A: No 5xx codes present → function returns None.

    For all route_metrics containing only 2xx/3xx/4xx codes (no 5xx),
    evaluate_upstream_error returns None regardless of threshold.

    **Validates: Requirements 3.1, 3.2**
    """

    @settings(max_examples=25)
    @given(data=non_5xx_route_metrics(), threshold=thresholds)
    def test_no_5xx_codes_returns_none(self, data, threshold):
        """When route_metrics has only non-5xx codes, result is always None."""
        route_metrics, route_id = data
        result = evaluate_upstream_error(route_metrics, route_id, threshold)
        assert result is None, (
            f"Expected None for non-5xx metrics, got {result}. "
            f"route_metrics={route_metrics}, threshold={threshold}"
        )


class TestPreservationPropertyB:
    """Property B: Total 5xx below threshold → function returns None.

    For all route_metrics where the total 5xx count (any 5xx codes)
    is below the threshold, evaluate_upstream_error returns None.

    **Validates: Requirements 3.3**
    """

    @settings(max_examples=25)
    @given(data=below_threshold_5xx_metrics())
    def test_5xx_below_threshold_returns_none(self, data):
        """When total 5xx count is below threshold, result is None."""
        route_metrics, route_id, threshold = data
        result = evaluate_upstream_error(route_metrics, route_id, threshold)
        assert result is None, (
            f"Expected None for below-threshold 5xx, got {result}. "
            f"route_metrics={route_metrics}, threshold={threshold}"
        )


class TestPreservationPropertyC:
    """Property C: Route not in metrics → function returns None.

    For any route_id that is NOT present in route_metrics,
    evaluate_upstream_error returns None.

    **Validates: Requirements 3.4**
    """

    @settings(max_examples=25)
    @given(
        route_id=route_ids,
        other_route_id=route_ids,
        threshold=thresholds,
    )
    def test_missing_route_returns_none(self, route_id, other_route_id, threshold):
        """When route_id is not in route_metrics, result is None."""
        assume(route_id != other_route_id)

        # Build metrics for a different route
        route_metrics = {other_route_id: {"200": 100, "502": 50}}

        result = evaluate_upstream_error(route_metrics, route_id, threshold)
        assert result is None, (
            f"Expected None for missing route '{route_id}', got {result}. "
            f"route_metrics keys={list(route_metrics.keys())}"
        )

    @settings(max_examples=15)
    @given(route_id=route_ids, threshold=thresholds)
    def test_empty_metrics_returns_none(self, route_id, threshold):
        """When route_metrics is completely empty, result is None."""
        result = evaluate_upstream_error({}, route_id, threshold)
        assert result is None, (
            f"Expected None for empty route_metrics, got {result}"
        )


class TestPreservationPropertyD:
    """Property D: Zero total traffic → function returns None.

    When route_metrics has the route but all counts sum to zero,
    evaluate_upstream_error returns None.

    **Validates: Requirements 3.4**
    """

    @settings(max_examples=15)
    @given(route_id=route_ids, threshold=thresholds)
    def test_zero_traffic_returns_none(self, route_id, threshold):
        """When route has zero total traffic, result is None."""
        # Empty dict for route means sum of values == 0
        route_metrics = {route_id: {}}
        result = evaluate_upstream_error(route_metrics, route_id, threshold)
        assert result is None, (
            f"Expected None for zero-traffic route, got {result}"
        )

    @settings(max_examples=15)
    @given(
        route_id=route_ids,
        threshold=thresholds,
        codes=st.lists(non_5xx_codes, min_size=1, max_size=5),
    )
    def test_zero_count_codes_returns_none(self, route_id, threshold, codes):
        """When all status codes have zero count, result is None."""
        metrics = {str(code): 0 for code in codes}
        route_metrics = {route_id: metrics}
        result = evaluate_upstream_error(route_metrics, route_id, threshold)
        assert result is None, (
            f"Expected None for zero-count metrics, got {result}"
        )
