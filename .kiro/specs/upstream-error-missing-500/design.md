# Upstream Error Missing 500 — Bugfix Design

## Overview

The `evaluate_upstream_error` function in `metrics_evaluator.py` only counts HTTP 502, 503, and 504 when evaluating upstream error conditions. HTTP 500 (Internal Server Error) and other 5xx codes (501, 505–599) are silently excluded, meaning genuine upstream failures go undetected by the UPSTREAM_ERROR alert rule. The sibling function `calculate_error_rate` already classifies all 5xx codes (500–599) correctly, so the fix is to align `evaluate_upstream_error` with that same range-based approach.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — when an upstream returns a 5xx code outside {502, 503, 504} (i.e., 500, 501, 505–599) and the threshold is met, the alert does not fire
- **Property (P)**: The desired behavior — `evaluate_upstream_error` SHALL count ALL status codes in the range 500–599 as upstream errors
- **Preservation**: Existing behavior for non-5xx inputs, threshold logic, other evaluator functions, and the `metric_values` structure for 502/503/504 that must remain unchanged
- **evaluate_upstream_error**: The function in `app/services/metrics_evaluator.py` that sums upstream error status codes and returns an `AlertContext` when the threshold is breached
- **calculate_error_rate**: The sibling function that already correctly classifies 500–599 as server errors using range comparison
- **AlertContext**: The Pydantic schema returned when an alert condition is met, containing `metric_values`, `threshold`, and evaluation window

## Bug Details

### Bug Condition

The bug manifests when an upstream service returns any 5xx status code that is NOT 502, 503, or 504 (most commonly HTTP 500). The `evaluate_upstream_error` function hardcodes only three specific codes rather than using a range check, so codes like 500, 501, 505, etc. are never counted toward the upstream error total.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type {route_metrics: Dict[str, Dict[str, float]], route_id: str, threshold: int}
  OUTPUT: boolean

  metrics := input.route_metrics.get(input.route_id)
  IF metrics IS None THEN RETURN False

  total := sum(metrics.values())
  IF total == 0 THEN RETURN False

  // Count all 5xx codes present
  all_5xx_count := 0
  FOR code, count IN metrics:
    IF 500 <= int(code) <= 599 THEN
      all_5xx_count += count

  // Count only the codes the current implementation checks
  old_count := metrics.get("502", 0) + metrics.get("503", 0) + metrics.get("504", 0)

  // Bug condition: there are 5xx errors the old code misses, AND
  // the full 5xx count meets the threshold (so an alert SHOULD fire)
  RETURN all_5xx_count > old_count
         AND all_5xx_count >= input.threshold
END FUNCTION
```

### Examples

- **HTTP 500 alone**: Route has `{"200": 100, "500": 5}`, threshold=3. Current code returns None (counts 0 upstream errors). Expected: alert fires with total_upstream_errors=5.
- **HTTP 500 + 502 combined**: Route has `{"200": 50, "500": 2, "502": 2}`, threshold=3. Current code counts only 2 (502). Expected: counts 4 (500+502), alert fires.
- **HTTP 501**: Route has `{"200": 200, "501": 10}`, threshold=5. Current code returns None. Expected: alert fires with total_upstream_errors=10.
- **Only 502/503/504 (no bug)**: Route has `{"200": 100, "502": 3, "503": 1}`, threshold=3. Current code correctly fires. Fix must preserve this behavior.
- **Below threshold**: Route has `{"200": 100, "500": 1}`, threshold=3. Neither old nor new code should fire an alert.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Routes with only 2xx/3xx responses must not trigger UPSTREAM_ERROR alerts
- 4xx status codes (400–499) must not be counted as upstream errors
- When total 5xx count is below the configured threshold, no alert fires
- When no metrics data exists for a route (route not in metrics dict), the function returns None
- `evaluate_jwt_failure` continues to operate independently evaluating 401/403 counts
- `evaluate_high_error_rate` continues with its existing 4xx+5xx classification and MIN_RESPONSES_FOR_RATE requirement
- The threshold comparison semantics (`>=`) remain unchanged
- The evaluation window (5-minute lookback) remains unchanged

**Scope:**
All inputs where the 5xx total (using the full 500–599 range) equals the old 502+503+504 total should produce identical results. The fix only changes behavior for inputs containing 5xx codes outside {502, 503, 504}.

## Hypothesized Root Cause

Based on the code analysis, the root cause is clear:

1. **Hardcoded status code list**: Lines in `evaluate_upstream_error` explicitly sum only three named codes:
   ```python
   count_502 = metrics.get("502", 0)
   count_503 = metrics.get("503", 0)
   count_504 = metrics.get("504", 0)
   upstream_error_count = count_502 + count_503 + count_504
   ```
   This was likely written with the assumption that APISIX only produces 502/503/504 as proxy errors, but upstreams can return any 5xx code (especially 500 for application-level failures).

2. **Inconsistency with `calculate_error_rate`**: The `calculate_error_rate` function already uses a range check (`500 <= code_int <= 599`), proving the project's intent is to treat all 5xx as server errors. The `evaluate_upstream_error` function was simply never updated to match.

3. **metric_values only reports 502/503/504**: The `AlertContext.metric_values` dict only includes `502_count`, `503_count`, `504_count`, meaning operators cannot see other 5xx codes in alert notifications even if they were counted.

## Correctness Properties

Property 1: Bug Condition — All 5xx codes counted as upstream errors

_For any_ input where the route metrics contain status codes in the range 500–599 and the sum of all 5xx counts meets or exceeds the threshold, the fixed `evaluate_upstream_error` function SHALL return a non-None `AlertContext` with `total_upstream_errors` equal to the sum of all 5xx response counts.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation — Non-5xx inputs produce identical results

_For any_ input where the route metrics contain NO status codes in the range 500–599, OR where the total 5xx count is below the threshold, the fixed `evaluate_upstream_error` function SHALL produce the same result as the original function (None), preserving the no-alert behavior for non-error traffic and below-threshold scenarios.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/services/metrics_evaluator.py`

**Function**: `evaluate_upstream_error`

**Specific Changes**:

1. **Replace hardcoded code lookups with range iteration**: Instead of `metrics.get("502", 0)` etc., iterate over all codes in `metrics` and sum those where `500 <= int(code) <= 599`. This mirrors the pattern already used in `calculate_error_rate` and `evaluate_high_error_rate`.

2. **Build a 5xx breakdown dict**: Collect individual 5xx code counts into a dict (e.g., `{"500": 3, "502": 1, "503": 2}`) for reporting in `metric_values`.

3. **Update metric_values in AlertContext**: Replace the static `502_count`/`503_count`/`504_count` keys with a dynamic breakdown of all observed 5xx codes, plus the `total_upstream_errors` sum. Example output:
   ```python
   metric_values={
       "5xx_breakdown": {"500": 3, "502": 1},
       "total_upstream_errors": 4,
   }
   ```

4. **Update docstring**: Change the docstring from "Sums 502, 503, and 504" to "Sums all 5xx (500–599) response counts".

5. **Apply same fix to PROD**: After verifying in UAT, apply identical change to `PROD/backend/app/services/metrics_evaluator.py`.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that `evaluate_upstream_error` ignores HTTP 500 and other non-{502,503,504} 5xx codes.

**Test Plan**: Write tests that supply route metrics containing 500, 501, 505 etc. codes above threshold and assert the function returns None (demonstrating the bug). Run these tests on the UNFIXED code to observe the defect.

**Test Cases**:
1. **HTTP 500 only**: Supply `{"500": 5}` with threshold=3, assert returns None (will demonstrate bug on unfixed code)
2. **HTTP 501 only**: Supply `{"501": 10}` with threshold=5, assert returns None (will demonstrate bug)
3. **Mixed 500+502**: Supply `{"500": 3, "502": 1}` with threshold=3, assert returns None because old code only counts 1 (will demonstrate bug)
4. **HTTP 505–599 range**: Supply `{"505": 2, "511": 3}` with threshold=4, assert returns None (will demonstrate bug)

**Expected Counterexamples**:
- Function returns None for all inputs containing only non-{502,503,504} 5xx codes
- Function undercounts when both "new" and "old" 5xx codes are present

### Fix Checking

**Goal**: Verify that for all inputs where 5xx codes exist at or above threshold, the fixed function returns a valid AlertContext.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := evaluate_upstream_error_fixed(input.route_metrics, input.route_id, input.threshold)
  ASSERT result IS NOT None
  ASSERT result.metric_values["total_upstream_errors"] == sum_all_5xx(input)
  ASSERT result.condition_type == ConditionType.UPSTREAM_ERROR
  ASSERT result.threshold == input.threshold
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT evaluate_upstream_error_original(input) == evaluate_upstream_error_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many random route metric combinations across the full status code space
- It catches edge cases like empty metrics, zero traffic, codes at threshold boundaries
- It provides strong guarantees that non-5xx and below-threshold behavior is unchanged

**Test Plan**: Observe behavior on UNFIXED code for non-5xx inputs and below-threshold 5xx inputs, then write property-based tests that assert the fixed code produces identical results.

**Test Cases**:
1. **No 5xx codes present**: Generate random route metrics with only 2xx/3xx/4xx codes, verify both old and new return None
2. **Below threshold**: Generate random 5xx counts that sum below the threshold, verify both return None
3. **No metrics for route**: Verify both return None when route_id is not in route_metrics
4. **Zero traffic**: Verify both return None when all counts sum to zero

### Unit Tests

- Test `evaluate_upstream_error` returns AlertContext when only HTTP 500 codes meet threshold
- Test correct `total_upstream_errors` sum for mixed 5xx codes (500+502+503+504+505)
- Test `metric_values` contains breakdown of all observed 5xx codes
- Test returns None when 5xx total is below threshold
- Test returns None when route has no metrics
- Test returns None when total traffic is zero
- Test 4xx codes are never included in upstream error count

### Property-Based Tests

- Generate random `route_metrics` with arbitrary status codes (200–599) and verify `evaluate_upstream_error` counts exactly and only 500–599 codes
- Generate random thresholds and verify the `>=` comparison is respected
- Generate inputs with no 5xx codes and verify the function always returns None (preservation)
- Generate inputs where old code and new code should agree (only 502/503/504 present) and verify identical AlertContext output

### Integration Tests

- Test that `notification_service` correctly dispatches alerts when upstream returns HTTP 500
- Test the full evaluation cycle: `fetch_route_metrics` → `evaluate_upstream_error` → alert context → notification
- Test that alert email/notification body includes the 5xx breakdown with all observed codes
