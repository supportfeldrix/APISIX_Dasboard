# Bugfix Requirements Document

## Introduction

The `evaluate_upstream_error` function in `metrics_evaluator.py` fails to trigger alerts for HTTP 500 responses from upstream services. It only counts status codes 502, 503, and 504, excluding HTTP 500 (Internal Server Error) and other 5xx codes (501, 505, etc.) from the upstream error count. This means genuine upstream failures (e.g., a route returning `x-apisix-upstream-status: 500`) go undetected by the UPSTREAM_ERROR alert condition.

The `HIGH_ERROR_RATE` evaluator does classify all 5xx codes correctly (500–599), but requires a minimum of 10 total responses and a rate threshold breach — so isolated or low-volume 500 errors do not trigger alerts through that path either.

The fix is to expand `evaluate_upstream_error` to count ALL 5xx status codes (500–599), making it consistent with how `calculate_error_rate` already classifies server errors.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN an upstream returns HTTP 500 and the UPSTREAM_ERROR alert rule threshold is met THEN the system does not fire a notification because `evaluate_upstream_error` only sums codes 502, 503, and 504

1.2 WHEN an upstream returns HTTP 501, 505, 506, 507, 508, or 510–599 and the UPSTREAM_ERROR alert rule threshold is met THEN the system does not fire a notification because those codes are excluded from the upstream error count

1.3 WHEN `evaluate_upstream_error` triggers an alert THEN the system only reports `502_count`, `503_count`, and `504_count` in `metric_values`, omitting 500 and other 5xx code counts from the alert context

### Expected Behavior (Correct)

2.1 WHEN an upstream returns HTTP 500 and the UPSTREAM_ERROR alert rule threshold is met THEN the system SHALL fire a notification by counting 500 as an upstream error

2.2 WHEN an upstream returns any status code in the range 500–599 and the UPSTREAM_ERROR alert rule threshold is met THEN the system SHALL fire a notification by counting all 5xx codes as upstream errors

2.3 WHEN `evaluate_upstream_error` triggers an alert THEN the system SHALL report the total 5xx count (sum of all codes 500–599) in `metric_values`, with a breakdown that includes all observed 5xx codes

### Unchanged Behavior (Regression Prevention)

3.1 WHEN an upstream returns only 2xx or 3xx status codes THEN the system SHALL CONTINUE TO not trigger UPSTREAM_ERROR alerts regardless of volume

3.2 WHEN an upstream returns 4xx status codes (400–499) THEN the system SHALL CONTINUE TO not count them as upstream errors in `evaluate_upstream_error`

3.3 WHEN the total 5xx count is below the configured threshold THEN the system SHALL CONTINUE TO not trigger an UPSTREAM_ERROR alert

3.4 WHEN there is no metrics data for a route (route not in metrics or zero total traffic) THEN the system SHALL CONTINUE TO return None without triggering an alert

3.5 WHEN the `evaluate_jwt_failure` function evaluates 401/403 counts THEN the system SHALL CONTINUE TO operate independently and without changes

3.6 WHEN the `evaluate_high_error_rate` function evaluates overall error rate THEN the system SHALL CONTINUE TO operate independently with its existing 4xx+5xx classification and MIN_RESPONSES_FOR_RATE requirement
