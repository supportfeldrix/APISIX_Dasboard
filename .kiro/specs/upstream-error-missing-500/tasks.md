# Implementation Plan

## Overview

Fix the `evaluate_upstream_error` function in `metrics_evaluator.py` to count ALL 5xx status codes (500–599) instead of only 502, 503, and 504. Uses exploration-first bug condition methodology: write tests to confirm the bug, write preservation tests to lock non-buggy behavior, then implement the fix.

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** — 5xx Codes Outside {502,503,504} Not Counted
  - **IMPORTANT**: Write this property-based test BEFORE implementing the fix
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate `evaluate_upstream_error` ignores HTTP 500 and other 5xx codes
  - **Scoped PBT Approach**: Use Hypothesis to generate status code dicts containing 5xx codes outside {502,503,504} (e.g., 500, 501, 505–599) with counts at or above threshold
  - Test file: `UAT/backend/tests/test_upstream_error_bug_condition.py`
  - Import `evaluate_upstream_error` from `app.services.metrics_evaluator`
  - Strategy: generate `route_metrics` dicts with at least one 5xx code ∈ {500,501,505–599} and total 5xx sum >= threshold
  - Assert that `evaluate_upstream_error(route_metrics, route_id, threshold)` returns a non-None `AlertContext`
  - Assert `result.metric_values["total_upstream_errors"]` equals the sum of all 5xx counts (500–599)
  - Assert `result.condition_type == ConditionType.UPSTREAM_ERROR`
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct — it proves the bug exists because the function returns None for 500/501/505+ codes)
  - Document counterexamples found (e.g., `evaluate_upstream_error({"500": 5}, route, 3)` returns None instead of AlertContext)
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** — Non-5xx and Below-Threshold Inputs Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **IMPORTANT**: Write and run these tests BEFORE implementing the fix
  - Test file: `UAT/backend/tests/test_upstream_error_preservation.py`
  - Observe behavior on UNFIXED code for non-buggy inputs:
    - Observe: `evaluate_upstream_error({"200": 100, "301": 5}, route, 3)` returns None
    - Observe: `evaluate_upstream_error({"200": 50, "404": 20}, route, 3)` returns None
    - Observe: `evaluate_upstream_error({"200": 100, "502": 1}, route, 3)` returns None (below threshold)
    - Observe: `evaluate_upstream_error({}, route, 3)` returns None (route not in metrics)
  - Write property-based tests using Hypothesis:
    - **Property A**: For all route_metrics containing only 2xx/3xx/4xx codes (no 5xx), function returns None regardless of threshold
    - **Property B**: For all route_metrics where total 5xx count (using any codes) is below threshold, function returns None
    - **Property C**: For route_id not present in route_metrics, function returns None
    - **Property D**: For route_metrics with zero total traffic, function returns None
  - Strategy: generate `route_metrics` dicts with codes drawn from `st.integers(200, 499)` and verify function returns None
  - Verify all tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Fix `evaluate_upstream_error` to count all 5xx codes (500–599)

  - [x] 3.1 Implement the fix in UAT/backend
    - File: `UAT/backend/app/services/metrics_evaluator.py`
    - Replace hardcoded `metrics.get("502", 0) + metrics.get("503", 0) + metrics.get("504", 0)` with range iteration over all codes where `500 <= int(code) <= 599`
    - Build a 5xx breakdown dict collecting individual code counts: `{"500": n, "502": m, ...}`
    - Update `metric_values` in the returned `AlertContext` to include `"total_upstream_errors"` (sum) and `"5xx_breakdown"` (dict of all observed 5xx codes)
    - Update the function docstring from "Sums 502, 503, and 504" to "Sums all 5xx (500–599) response counts"
    - _Bug_Condition: isBugCondition(input) where route has 5xx codes outside {502,503,504} and total 5xx >= threshold_
    - _Expected_Behavior: evaluate_upstream_error returns AlertContext with total_upstream_errors = sum of all 500–599 codes when sum >= threshold_
    - _Preservation: Non-5xx inputs, below-threshold inputs, missing routes, and other evaluator functions remain unchanged_
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** — All 5xx Codes Counted as Upstream Errors
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior (returns AlertContext for all 5xx codes at/above threshold)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run: `python -m pytest tests/test_upstream_error_bug_condition.py -v --tb=short`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** — Non-5xx and Below-Threshold Inputs Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run: `python -m pytest tests/test_upstream_error_preservation.py -v --tb=short`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm non-5xx inputs, below-threshold inputs, and missing routes still return None
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 3.4 Apply identical fix to PROD/backend
    - File: `PROD/backend/app/services/metrics_evaluator.py`
    - Apply the exact same changes as UAT (range iteration, 5xx breakdown, metric_values update, docstring)
    - Run PROD tests: `python -m pytest tests/test_upstream_error_bug_condition.py tests/test_upstream_error_preservation.py -v --tb=short`
    - Confirm both test suites pass in PROD environment
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

- [x] 4. Checkpoint — Ensure all tests pass
  - Run full test suite in UAT: `python -m pytest tests/ -v --tb=short`
  - Run full test suite in PROD: `python -m pytest tests/ -v --tb=short`
  - Verify no regressions in `evaluate_jwt_failure` or `evaluate_high_error_rate`
  - Ignore Hypothesis `DeadlineExceeded` timing flakes (per project convention)
  - Ensure all tests pass, ask the user if questions arise


## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4"] },
    { "id": 3, "tasks": ["4"] }
  ]
}
```

## Notes

- Both UAT and PROD backends have separate copies of `metrics_evaluator.py` — fix must be applied to both
- Tests use pytest with Hypothesis for property-based testing
- `DeadlineExceeded` flakes from Hypothesis are expected and can be ignored (per project convention)
- The `calculate_error_rate` function already uses the correct 500–599 range — use its pattern as reference for the fix
- Test files should be placed in the `tests/` directory alongside existing test modules
