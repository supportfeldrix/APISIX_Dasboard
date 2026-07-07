"""Bug condition exploration test for evaluate_upstream_error.

**Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3**

This test is written BEFORE the fix to confirm the bug exists.
It SHOULD FAIL on unfixed code — failure proves the bug is real.

The bug: evaluate_upstream_error only counts HTTP 502, 503, 504.
It ignores HTTP 500 and other 5xx codes (501, 505–599), meaning
genuine upstream failures go undetected by the UPSTREAM_ERROR alert.
"""
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.metrics_evaluator import evaluate_upstream_error
from app.schemas.notifications import ConditionType


# 5xx codes that the CURRENT (buggy) implementation does NOT count
MISSING_5XX_CODES = [500, 501] + list(range(505, 600))

# All 5xx codes (the full range that SHOULD be counted)
ALL_5XX_CODES = list(range(500, 600))


def sum_all_5xx(metrics: dict) -> float:
    """Sum all 5xx status code counts in a metrics dict."""
    total = 0.0
    for code, count in metrics.items():
        try:
            code_int = int(code)
        except (ValueError, TypeError):
            continue
        if 500 <= code_int <= 599:
            total += count
    return total


# Strategy: generate route metrics containing at least one 5xx code
# outside {502, 503, 504} with total 5xx sum >= threshold
@st.composite
def bug_condition_metrics(draw):
    """Generate route_metrics that trigger the bug condition.

    Produces a metrics dict with:
    - At least one 5xx code NOT in {502, 503, 504}
    - Total 5xx count >= threshold
    - Some background 2xx traffic to make it realistic
    """
    # Pick at least one "missing" 5xx code (the ones the bug ignores)
    num_missing_codes = draw(st.integers(min_value=1, max_value=3))
    missing_codes = draw(
        st.lists(
            st.sampled_from(MISSING_5XX_CODES),
            min_size=num_missing_codes,
            max_size=num_missing_codes,
            unique=True,
        )
    )

    # Optionally include some of the "old" codes (502, 503, 504)
    old_codes = draw(
        st.lists(
            st.sampled_from([502, 503, 504]),
            min_size=0,
            max_size=2,
            unique=True,
        )
    )

    # Generate counts for each 5xx code (at least 1 each)
    metrics = {}
    for code in missing_codes:
        metrics[str(code)] = draw(st.integers(min_value=1, max_value=20))
    for code in old_codes:
        metrics[str(code)] = draw(st.integers(min_value=1, max_value=10))

    # Add some 2xx background traffic
    metrics["200"] = draw(st.integers(min_value=10, max_value=200))

    # Calculate total 5xx and pick a threshold that is <= total
    total_5xx = sum_all_5xx(metrics)
    assume(total_5xx >= 1)

    # Threshold must be <= total_5xx so the alert SHOULD fire
    threshold = draw(st.integers(min_value=1, max_value=int(total_5xx)))

    return metrics, threshold


@settings(max_examples=15, deadline=None)
@given(data=bug_condition_metrics())
def test_bug_condition_5xx_codes_outside_502_503_504_not_counted(data):
    """Property 1: Bug Condition — 5xx Codes Outside {502,503,504} Not Counted.

    **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3**

    For any route_metrics containing 5xx codes outside {502, 503, 504}
    where the total 5xx count meets or exceeds the threshold, the function
    SHALL return a non-None AlertContext with correct total_upstream_errors.

    On UNFIXED code, this test is EXPECTED TO FAIL because the function
    ignores codes like 500, 501, 505+ and returns None.
    """
    metrics, threshold = data
    route_id = "test_route"
    route_metrics = {route_id: metrics}

    # The function should detect the upstream errors and return an AlertContext
    result = evaluate_upstream_error(route_metrics, route_id, threshold)

    # Assert non-None (the fix should return an alert)
    assert result is not None, (
        f"evaluate_upstream_error returned None for metrics={metrics} "
        f"with threshold={threshold}. Total 5xx={sum_all_5xx(metrics)}. "
        f"Bug confirmed: function ignores 5xx codes outside {{502, 503, 504}}"
    )

    # Assert correct total upstream error count
    expected_total = sum_all_5xx(metrics)
    assert result.metric_values["total_upstream_errors"] == expected_total, (
        f"Expected total_upstream_errors={expected_total}, "
        f"got {result.metric_values['total_upstream_errors']}"
    )

    # Assert correct condition type
    assert result.condition_type == ConditionType.UPSTREAM_ERROR, (
        f"Expected condition_type=UPSTREAM_ERROR, got {result.condition_type}"
    )
