# Requirements Document

## Introduction

This feature adds email notification capabilities to the APISIX Dashboard application. When vendor routes experience failures — such as JWT token rejections, upstream unavailability, or high error rates — the system will automatically send email alerts to the configured team members. This enables proactive incident response without requiring constant manual monitoring of the dashboard.

The notification system integrates with the existing Prometheus metrics scraping service to detect failure conditions and uses SMTP to deliver email alerts. It includes configurable thresholds, cooldown periods to prevent alert fatigue, and a management UI for notification rules.

## Glossary

- **Notification_Service**: The backend service responsible for evaluating alert conditions against scraped metrics and dispatching email notifications.
- **Alert_Rule**: A user-defined configuration that specifies which route, failure condition, threshold, and recipients trigger an email notification.
- **Metrics_Evaluator**: The component within the Notification_Service that periodically queries Prometheus metrics and compares them against configured Alert_Rules.
- **SMTP_Dispatcher**: The component responsible for formatting and sending email messages via the configured SMTP server.
- **Cooldown_Period**: A configurable time window after an alert is sent during which duplicate alerts for the same condition are suppressed.
- **Error_Rate**: The percentage of responses with HTTP status codes indicating failure (4xx/5xx) relative to total requests for a given route within a time window.
- **Route**: An APISIX gateway route that proxies traffic between vendors.
- **Notification_Log**: A database record of all sent notifications including timestamp, recipients, route, and alert condition.
- **Health_Check_Probe**: A periodic HTTP request sent to a route's upstream to verify availability independently of live traffic.

## Requirements

### Requirement 1: SMTP Configuration

**User Story:** As an administrator, I want to configure SMTP server settings for the dashboard, so that the system can send email notifications.

#### Acceptance Criteria

1. THE Notification_Service SHALL load SMTP configuration from environment variables (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_ADDRESS, SMTP_USE_TLS), where SMTP_HOST, SMTP_PORT, and SMTP_FROM_ADDRESS are required, SMTP_USERNAME and SMTP_PASSWORD are optional (defaulting to no authentication), and SMTP_USE_TLS defaults to true if not specified.
2. WHEN the application starts, THE Notification_Service SHALL validate that all required SMTP settings (SMTP_HOST, SMTP_PORT, SMTP_FROM_ADDRESS) are present, that SMTP_PORT is an integer between 1 and 65535, and that SMTP_FROM_ADDRESS is a valid email format, and SHALL log a warning at WARNING level if email notifications are disabled due to missing or invalid configuration.
3. WHEN an administrator sends a test email via the API, THE SMTP_Dispatcher SHALL attempt to connect to the configured SMTP server within 10 seconds, send a test message to the specified address, and return a response indicating success or failure with a human-readable reason for failure.
4. IF the SMTP server is unreachable during a notification attempt, THEN THE Notification_Service SHALL log the failure including the recipient address and error reason, and retry delivery up to 3 times with exponential backoff starting at 2 seconds (2s, 4s, 8s).
5. IF all 3 retry attempts fail, THEN THE Notification_Service SHALL log an error indicating permanent delivery failure for the notification and discard the delivery attempt.

### Requirement 2: Alert Rule Management

**User Story:** As an administrator, I want to create and manage alert rules that define when email notifications should be sent, so that I can tailor notifications to specific routes and failure conditions.

#### Acceptance Criteria

1. THE Notification_Service SHALL support creating Alert_Rules with the following fields: rule name (1 to 128 characters, alphanumeric, hyphens, and underscores), target route ID, failure condition type, threshold value (integer from 1 to 10000 for count-based conditions, or 1 to 100 for percentage-based conditions), a list of 1 to 10 recipient email addresses, cooldown period (60 to 86400 seconds), and enabled status (boolean).
2. WHEN an administrator submits a valid Alert_Rule creation request via the API, THE Notification_Service SHALL validate that the rule name is unique, the target route ID references an existing route, all recipient email addresses conform to standard email format, and the threshold and cooldown values are within their defined ranges, and SHALL persist the rule to the database.
3. IF any field in an Alert_Rule creation or update request fails validation, THEN THE Notification_Service SHALL reject the request, return an error response indicating which fields failed validation and why, and SHALL NOT persist any changes.
4. IF the target route ID in an Alert_Rule creation or update request does not reference an existing route, THEN THE Notification_Service SHALL reject the request with an error response indicating the route was not found.
5. WHEN an administrator updates an existing Alert_Rule, THE Notification_Service SHALL apply changes so they take effect on the next evaluation cycle occurring after the update is persisted.
6. WHEN an administrator deletes an Alert_Rule, THE Notification_Service SHALL remove the rule from the database and cease evaluating it from the next evaluation cycle onward.
7. THE Notification_Service SHALL expose a REST API endpoint to list all configured Alert_Rules with their current status, returning a maximum of 100 rules per response page.
8. THE Notification_Service SHALL support the following failure condition types: JWT_FAILURE (triggered by 401 or 403 HTTP responses), UPSTREAM_ERROR (triggered by 502, 503, or 504 HTTP responses), HIGH_ERROR_RATE (triggered when error percentage exceeds the configured threshold value within the evaluation window), and HEALTH_CHECK_FAILURE (triggered when a route health check endpoint fails to respond with a success status).

### Requirement 3: JWT Token Failure Detection

**User Story:** As a team member, I want to be notified when a vendor's requests are being rejected due to JWT token issues, so that I can investigate and resolve authentication problems promptly.

#### Acceptance Criteria

1. WHEN the Metrics_Evaluator detects that a route's combined count of 401 and 403 responses meets or exceeds the configured threshold (range: 1–1000, default: 5) within a 5-minute evaluation window, THE Notification_Service SHALL trigger the associated Alert_Rule.
2. WHEN a JWT_FAILURE alert is triggered, THE SMTP_Dispatcher SHALL send an email containing the route name, route ID, the count of 401/403 responses, the evaluation time window, and a timestamp.
3. WHILE a Cooldown_Period is active for a JWT_FAILURE Alert_Rule (starting from the moment the notification email is dispatched), THE Notification_Service SHALL suppress duplicate notifications for the same route and condition.
4. IF the Metrics_Evaluator receives no metric data for a monitored route during the 5-minute evaluation window, THEN THE Notification_Service SHALL skip evaluation for that route and log the absence without triggering an alert.

### Requirement 4: Upstream Unavailability Detection

**User Story:** As a team member, I want to be notified when a vendor's upstream service is down, so that I can escalate and coordinate resolution with the vendor.

#### Acceptance Criteria

1. WHEN the Metrics_Evaluator detects that a route's combined count of 502, 503, and 504 responses exceeds the configured threshold within a 5-minute evaluation window, THE Notification_Service SHALL trigger the associated Alert_Rule.
2. WHEN an UPSTREAM_ERROR alert is triggered, THE SMTP_Dispatcher SHALL send an email to the Alert_Rule's configured recipients containing the route name, route ID, the count of responses broken down by status code (502, 503, 504), the evaluation time window start and end timestamps, and the alert trigger timestamp.
3. WHILE a Cooldown_Period is active for an UPSTREAM_ERROR Alert_Rule, THE Notification_Service SHALL suppress duplicate notifications for the same route and condition.
4. WHEN a Cooldown_Period expires and the Metrics_Evaluator detects that the route's combined 502, 503, and 504 response count still exceeds the configured threshold, THE Notification_Service SHALL trigger the Alert_Rule again.
5. IF the Metrics_Evaluator detects zero total requests for a route within the evaluation window, THEN THE Notification_Service SHALL skip threshold evaluation for that route and not trigger an alert.
6. WHEN the Metrics_Evaluator detects that a route's combined 502, 503, and 504 response count returns to or below the configured threshold after a previously triggered UPSTREAM_ERROR alert, THE Notification_Service SHALL send a recovery notification to the Alert_Rule's configured recipients indicating the route has recovered.

### Requirement 5: High Error Rate Threshold Detection

**User Story:** As a team member, I want to be notified when a route's overall error rate exceeds a configurable threshold, so that I can detect degraded service quality.

#### Acceptance Criteria

1. WHEN the Metrics_Evaluator calculates that a route's Error_Rate is strictly greater than the threshold percentage defined in the Alert_Rule within a 5-minute evaluation window, and the route has received at least 10 total responses within that window, THE Notification_Service SHALL trigger the associated Alert_Rule.
2. THE Metrics_Evaluator SHALL calculate Error_Rate as the number of 4xx and 5xx responses divided by total responses for the route within the evaluation window, expressed as a percentage rounded to two decimal places.
3. IF the total response count for a route is zero within the evaluation window, THEN THE Metrics_Evaluator SHALL skip evaluation for that route and not trigger any HIGH_ERROR_RATE Alert_Rule.
4. WHEN a HIGH_ERROR_RATE alert is triggered, THE SMTP_Dispatcher SHALL send an email containing the route name, route ID, the calculated error rate percentage, the threshold value, the total number of requests evaluated, and a timestamp.
5. WHILE a Cooldown_Period is active for a HIGH_ERROR_RATE Alert_Rule, THE Notification_Service SHALL suppress duplicate notifications for the same route and condition.

### Requirement 6: Route Health Check Probing

**User Story:** As a team member, I want the system to periodically probe route health independently of live traffic, so that I am notified of failures even when no vendor traffic is flowing.

#### Acceptance Criteria

1. WHEN a Health_Check_Probe is configured for a route, THE Notification_Service SHALL send an HTTP GET request to the route's upstream URL at the configured interval (default: 60 seconds, minimum: 10 seconds, maximum: 3600 seconds).
2. WHEN a Health_Check_Probe receives a non-2xx HTTP response, a connection error, a DNS resolution failure, or does not receive a response within 10 seconds, THE Notification_Service SHALL mark the probe as failed.
3. WHEN a Health_Check_Probe fails for a configured number of consecutive attempts (default: 3, minimum: 1, maximum: 10), THE Notification_Service SHALL trigger the associated HEALTH_CHECK_FAILURE Alert_Rule.
4. WHEN a previously failing Health_Check_Probe returns a 2xx response for 2 consecutive probes, THE Notification_Service SHALL send a recovery notification to the Alert_Rule recipients.
5. WHILE a Cooldown_Period (default: 300 seconds) is active for a HEALTH_CHECK_FAILURE Alert_Rule, THE Notification_Service SHALL suppress duplicate failure notifications for the same route.
6. WHEN a Health_Check_Probe sends a request, THE Notification_Service SHALL include a distinguishing User-Agent header identifying the request as a health-check probe.

### Requirement 7: Notification Logging and History

**User Story:** As an administrator, I want to view a history of all sent notifications, so that I can audit alert activity and verify the system is working correctly.

#### Acceptance Criteria

1. WHEN the SMTP_Dispatcher sends or fails to send a notification email, THE Notification_Service SHALL persist a Notification_Log record containing: timestamp, Alert_Rule ID, route ID, route name, failure condition type, recipient addresses, email subject, delivery status (one of: SENT, FAILED, RETRYING), and error message if delivery failed.
2. THE Notification_Service SHALL expose a REST API endpoint to query Notification_Log records with filtering by route, condition type, date range, and delivery status, with pagination defaulting to 25 entries per page and sorted by timestamp descending.
3. THE Notification_Service SHALL retain Notification_Log records for a configurable duration (default: 90 days) and automatically purge older records once per day during a scheduled maintenance window.

### Requirement 8: Background Evaluation Scheduler

**User Story:** As a system operator, I want the metrics evaluation to run automatically on a schedule, so that alerts are generated without manual intervention.

#### Acceptance Criteria

1. WHEN the application starts and SMTP configuration is valid, THE Notification_Service SHALL start a background scheduler that evaluates all enabled Alert_Rules at a configurable interval (default: 60 seconds, minimum: 10 seconds, maximum: 3600 seconds).
2. WHEN an evaluation cycle begins, THE Metrics_Evaluator SHALL fetch current metrics from the existing Prometheus metrics endpoint using the configured request timeout.
3. IF the Metrics_Evaluator encounters an error fetching metrics, THEN THE Notification_Service SHALL log the error, skip evaluation of all Alert_Rules for that cycle, and resume evaluation on the next scheduled cycle without crashing.
4. IF an evaluation cycle is still in progress when the next cycle is due, THEN THE Notification_Service SHALL skip the pending cycle and log a warning indicating the overlap.
5. WHEN the application shuts down, THE Notification_Service SHALL stop the background scheduler and allow in-progress evaluations to complete up to a maximum of 30 seconds before forcing termination.
6. IF SMTP configuration is missing or invalid at application start, THEN THE Notification_Service SHALL log a warning and NOT start the background scheduler.

### Requirement 9: Notification Management UI

**User Story:** As an administrator, I want a UI page in the dashboard to manage alert rules and view notification history, so that I can configure notifications without direct API calls.

#### Acceptance Criteria

1. THE Dashboard SHALL provide a notifications management page accessible from the main navigation menu.
2. THE Dashboard SHALL display a table of all configured Alert_Rules showing rule name, target route, condition type, threshold, recipients, cooldown period, and enabled status.
3. WHEN an administrator clicks "Create Rule", THE Dashboard SHALL display a form to configure a new Alert_Rule with fields for rule name (maximum 128 characters), target route (selected from existing routes), failure condition type, threshold value, recipient email addresses (maximum 10 recipients), cooldown period (in minutes), and enabled status, and SHALL display inline validation errors for any field that fails validation before allowing submission.
4. WHEN an administrator selects an existing Alert_Rule for editing, THE Dashboard SHALL display the rule's current values in the form and allow the administrator to update and save changes via the API.
5. WHEN an administrator requests deletion of an Alert_Rule, THE Dashboard SHALL require explicit confirmation before sending the delete request to the API.
6. WHEN an administrator toggles an Alert_Rule's enabled status, THE Dashboard SHALL send the update request to the API and reflect the new status in the table within 2 seconds.
7. IF an API request initiated from the notifications management page fails, THEN THE Dashboard SHALL display an error message indicating the nature of the failure and preserve any unsaved form data.
8. THE Dashboard SHALL provide a notification history tab showing Notification_Log entries with filtering by route, condition type, date range, and delivery status, and with pagination defaulting to 25 entries per page.
9. WHEN an administrator clicks "Send Test Email" on the settings page, THE Dashboard SHALL invoke the test email API endpoint and display a success or failure indication with the delivery status returned by the API.
