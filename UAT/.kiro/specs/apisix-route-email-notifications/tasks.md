# Implementation Plan: APISIX Route Email Notifications

## Overview

This plan implements an email notification subsystem for the APISIX Dashboard. The system monitors route health via Prometheus metrics and active health-check probes, evaluates user-defined alert rules on a configurable schedule, and dispatches email notifications through SMTP when thresholds are breached. Implementation follows the existing FastAPI/SQLAlchemy/Vue.js patterns already established in the project.

## Tasks

- [x] 1. Set up configuration, data models, and schemas
  - [x] 1.1 Extend app/config.py with SMTP and notification settings
    - Add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_ADDRESS, SMTP_USE_TLS fields
    - Add NOTIFICATION_EVAL_INTERVAL and NOTIFICATION_LOG_RETENTION_DAYS fields
    - _Requirements: 1.1, 1.2, 8.1_

  - [x] 1.2 Create app/models/alert_rule.py SQLAlchemy model
    - Define AlertRule table with all columns (name, route_id, condition_type, threshold, recipients, cooldown_seconds, enabled, health_check fields, timestamps)
    - Add appropriate indexes on name, route_id, condition_type
    - _Requirements: 2.1, 2.8_

  - [x] 1.3 Create app/models/notification_log.py SQLAlchemy model
    - Define NotificationLog table with all columns (timestamp, alert_rule_id, route_id, condition_type, recipients, subject, delivery_status, error_message)
    - Add foreign key to alert_rules with SET NULL on delete
    - Add indexes on timestamp, route_id, condition_type, delivery_status
    - _Requirements: 7.1_

  - [x] 1.4 Create app/schemas/notifications.py Pydantic schemas
    - Define ConditionType enum, AlertRuleCreate, AlertRuleUpdate, AlertRuleResponse schemas
    - Define NotificationLogResponse, PaginatedLogs, LogFilters schemas
    - Define AlertContext and DeliveryResult dataclasses
    - Add validation constraints (name pattern, threshold ranges, recipient count, cooldown range)
    - _Requirements: 2.1, 2.3, 7.2_

  - [ ]* 1.5 Write property test for alert rule validation (Property 1)
    - **Property 1: Alert rule validation accepts valid inputs and rejects invalid inputs**
    - **Validates: Requirements 2.1, 2.2, 2.3**

- [ ] 2. Implement core notification services
  - [x] 2.1 Create app/services/metrics_evaluator.py
    - Implement evaluate_jwt_failure: sum 401+403 counts per route, compare against threshold
    - Implement evaluate_upstream_error: sum 502+503+504 counts per route, compare against threshold
    - Implement evaluate_high_error_rate: calculate (4xx+5xx)/total*100, compare against threshold
    - Implement calculate_error_rate helper with minimum 10 responses guard
    - _Requirements: 3.1, 4.1, 5.1, 5.2, 5.3_

  - [ ]* 2.2 Write property test for count-based threshold evaluation (Property 3)
    - **Property 3: Count-based threshold evaluation triggers correctly**
    - **Validates: Requirements 3.1, 4.1**

  - [ ]* 2.3 Write property test for error rate calculation (Property 4)
    - **Property 4: Error rate calculation and threshold evaluation**
    - **Validates: Requirements 5.1, 5.2**

  - [x] 2.4 Create app/services/smtp_dispatcher.py
    - Implement send_notification with aiosmtplib, retry logic (3 attempts, exponential backoff 2s/4s/8s)
    - Implement send_test_email for connectivity verification
    - Implement format_alert_email with condition-type-specific content
    - Implement format_recovery_email for recovery notifications
    - Handle auth failures (no retry), timeouts, unreachable server
    - _Requirements: 1.3, 1.4, 1.5, 3.2, 4.2, 5.4_

  - [ ]* 2.5 Write property test for alert email content (Property 6)
    - **Property 6: Alert email contains all required fields for condition type**
    - **Validates: Requirements 3.2, 4.2, 5.4**

  - [x] 2.6 Create app/services/notification_service.py
    - Implement should_notify with cooldown check logic
    - Implement trigger_alert: check cooldown, dispatch email, persist log
    - Implement check_recovery: detect threshold return to normal, send recovery email
    - Implement CRUD operations: create_rule, update_rule, delete_rule, get_rules
    - Implement get_notification_logs with filtering and pagination
    - Implement purge_old_logs based on retention days
    - Validate route existence on create/update
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.3, 4.3, 4.4, 4.6, 5.5, 7.1, 7.2, 7.3_

  - [ ]* 2.7 Write property test for cooldown suppression (Property 5)
    - **Property 5: Cooldown suppression prevents duplicate notifications**
    - **Validates: Requirements 3.3, 4.3, 4.4, 5.5, 6.5**

  - [ ]* 2.8 Write property test for pagination (Property 2)
    - **Property 2: Alert rule pagination returns correct pages**
    - **Validates: Requirements 2.7**

- [ ] 3. Checkpoint - Core services verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement health check prober and background scheduler
  - [x] 4.1 Create app/services/health_check_prober.py
    - Implement probe_route: async HTTP GET with 10s timeout, custom User-Agent header
    - Implement update_state: track consecutive failures/successes per route
    - Classify responses: 2xx = success, all else (non-2xx, connection error, DNS failure, timeout) = failure
    - Trigger alert at configured consecutive failure threshold
    - Trigger recovery after 2 consecutive successes from unhealthy state
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 4.2 Write property test for probe result classification (Property 7)
    - **Property 7: Health check probe result classification**
    - **Validates: Requirements 6.2**

  - [ ]* 4.3 Write property test for consecutive failure detection (Property 8)
    - **Property 8: Consecutive failure detection triggers at threshold**
    - **Validates: Requirements 6.3**

  - [ ]* 4.4 Write property test for health check recovery (Property 9)
    - **Property 9: Health check recovery detection after consecutive successes**
    - **Validates: Requirements 6.4**

  - [ ]* 4.5 Write property test for upstream recovery (Property 10)
    - **Property 10: Upstream recovery detection**
    - **Validates: Requirements 4.6**

  - [x] 4.6 Create app/services/background_scheduler.py
    - Implement start/stop lifecycle tied to FastAPI lifespan
    - Implement _run_cycle: fetch metrics, load enabled rules, evaluate each, run health probes
    - Handle overlap detection (skip cycle if previous still running)
    - Handle evaluation errors gracefully (log and continue)
    - Allow 30s graceful shutdown for in-progress evaluations
    - Only start if SMTP configuration is valid
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ] 5. Implement REST API router and wire into application
  - [x] 5.1 Create app/routers/notifications.py
    - Implement GET /api/notifications/rules (paginated list)
    - Implement POST /api/notifications/rules (create with validation)
    - Implement GET /api/notifications/rules/{id} (single rule)
    - Implement PUT /api/notifications/rules/{id} (update)
    - Implement DELETE /api/notifications/rules/{id} (delete)
    - Implement PATCH /api/notifications/rules/{id}/toggle (enable/disable)
    - Implement GET /api/notifications/logs (filtered, paginated)
    - Implement POST /api/notifications/test-email (send test)
    - Implement GET /api/notifications/status (scheduler status)
    - All endpoints require JWT auth via get_current_user dependency
    - _Requirements: 1.3, 2.2, 2.5, 2.6, 2.7, 7.2, 9.9_

  - [x] 5.2 Register router and scheduler in app/main.py
    - Import and include notifications router with /api prefix
    - Import AlertRule and NotificationLog models in lifespan for table creation
    - Start background scheduler in lifespan startup
    - Stop background scheduler in lifespan shutdown
    - _Requirements: 8.1, 8.5_

  - [ ]* 5.3 Write property test for notification log completeness (Property 11)
    - **Property 11: Notification log record completeness**
    - **Validates: Requirements 7.1**

  - [ ]* 5.4 Write property test for log filtering (Property 12)
    - **Property 12: Notification log filtering returns only matching records**
    - **Validates: Requirements 7.2**

  - [ ]* 5.5 Write property test for log purge (Property 13)
    - **Property 13: Log purge removes exactly expired records**
    - **Validates: Requirements 7.3**

- [ ] 6. Checkpoint - Backend integration verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement frontend notification management UI
  - [x] 7.1 Create frontend/src/api/notifications.js API client
    - Implement functions for all notification endpoints (getRules, createRule, updateRule, deleteRule, toggleRule, getLogs, sendTestEmail, getStatus)
    - Use existing axios client from frontend/src/api/client.js
    - _Requirements: 9.2, 9.3, 9.4, 9.5, 9.6, 9.8, 9.9_

  - [x] 7.2 Create frontend/src/components/AlertRuleForm.jsx
    - Build modal form with fields: name, route selector (dropdown), condition type, threshold, recipients (tag input), cooldown, enabled toggle
    - Add conditional fields for HEALTH_CHECK_FAILURE (URL, interval, failure threshold)
    - Implement inline validation (name length/pattern, email format, threshold range, cooldown range)
    - Support both create and edit modes
    - _Requirements: 9.3, 9.4, 9.7_

  - [x] 7.3 Create frontend/src/pages/Notifications.jsx
    - Implement two-tab layout: Alert Rules tab and Notification History tab
    - Alert Rules tab: table with name, route, condition, threshold, recipients, cooldown, enabled toggle, edit/delete actions
    - Notification History tab: filterable table with route, condition type, date range, delivery status filters, pagination (25/page)
    - Add "Create Rule" button opening AlertRuleForm modal
    - Add delete confirmation dialog
    - Display API error messages and preserve unsaved form data on failure
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [x] 7.4 Add Notifications page to navigation and routing in App.jsx
    - Add route entry for /notifications path
    - Add navigation menu item for Notifications page
    - _Requirements: 9.1_

- [ ] 8. Final checkpoint - Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The only new backend dependency is `aiosmtplib` — add it to requirements.txt in task 2.4
- Frontend follows existing patterns: JSX pages, axios-based API client, Tailwind CSS styling

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.5", "2.1", "2.4"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.5", "2.6", "4.1"] },
    { "id": 4, "tasks": ["2.7", "2.8", "4.2", "4.3", "4.4", "4.5", "4.6"] },
    { "id": 5, "tasks": ["5.1", "7.1"] },
    { "id": 6, "tasks": ["5.2", "5.3", "5.4", "5.5"] },
    { "id": 7, "tasks": ["7.2"] },
    { "id": 8, "tasks": ["7.3"] },
    { "id": 9, "tasks": ["7.4"] }
  ]
}
```
