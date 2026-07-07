# Implementation Plan: ControlM Escalation

## Overview

This plan implements automated phone-call escalation via ControlM trigger files for the APISIX Dashboard. The implementation follows the existing service-based architecture: SQLAlchemy models first, then service classes, FastAPI router, integration into the BackgroundScheduler, and finally React frontend components. Code is split across dedicated files following the established pattern (models/, services/, routers/, src/pages/, src/components/).

## Tasks

- [x] 1. Database models and migrations
  - [x] 1.1 Create SQLAlchemy models for escalation state and log
    - Create `app/models/escalation_state.py` with `EscalationState` model (rule_id PK, state, grace_started_at, grace_expires_at, escalated_at, trigger_file, failure_message)
    - Create `app/models/escalation_log.py` with `EscalationLog` model (id, rule_id FK, rule_name, event_type, file_path, username, error_msg, created_at) with indexes on (rule_id, created_at) and (created_at)
    - Create `app/models/controlm_settings.py` with `ControlMSettings` model (id=1 singleton, controlm_enabled, landing_zone, grace_period, updated_at)
    - Add columns to `AlertRule` model: `notify_controlm = Column(Boolean, default=False)`, `critical = Column(Boolean, default=False)`
    - Register all new models in `app/models/__init__.py`
    - Add `Base.metadata.create_all(bind=engine)` call or Alembic migration to create tables on startup
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 4.4, 5.1_

- [x] 2. Core logic — TriggerFileWriter service
  - [x] 2.1 Implement TriggerFileWriter in app/services/controlm_trigger_writer.py
    - Create `TriggerFileWriter` class with methods: `write_trigger_file()`, `write_recovery_file()`, `sanitize_name()`, `format_file_content()`, `_get_landing_zone()`, `_atomic_write()`
    - `sanitize_name()`: replace non-alphanumeric chars (except `_`) with `_`, truncate to 100 chars, return `UNKNOWN` if result is empty
    - `format_file_content()`: KEY=VALUE pairs on separate lines (rule_name, route_id, route_name, condition_type, failure_message truncated to 500 chars, alert_timestamp ISO 8601 UTC, severity CRITICAL/WARNING)
    - `_atomic_write()`: write to temp file in landing zone, then `os.rename()` to final path
    - File naming: `CROIT_ALERT_{sanitized_name}_{YYYYMMDD_HHMMSS}.trigger` for alerts, `CROIT_RECOVERY_{sanitized_name}_{YYYYMMDD_HHMMSS}.trigger` for recovery
    - Wrap all file operations in try/except, return (success, path_or_error) tuples
    - Read landing zone from `ControlMSettings` singleton row via `SessionLocal()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 4.1_

  - [ ]* 2.2 Write property tests for trigger file name and content format
    - **Property 2: Trigger File Name Format** — sanitization, truncation, UNKNOWN fallback
    - **Property 3: Trigger File Content Format** — KEY=VALUE format, truncation, severity
    - **Property 13: Recovery File Generation** — same sanitization rules
    - Create `tests/test_controlm_escalation.py`
    - _Validates: Requirements 1.2, 1.3, 1.6, 1.7, 4.1_

- [x] 3. Core logic — EscalationService
  - [x] 3.1 Implement EscalationService in app/services/controlm_escalation_service.py
    - Create `EscalationService` class with `_pending_tasks` dict and `asyncio.Lock`
    - Implement `handle_alert_triggered(rule, context, db)`: check global toggle + per-rule `notify_controlm`, determine effective grace period, decide immediate escalation vs grace period countdown
    - Implement `_get_effective_grace_period(rule, db)`: return 0 if critical flag set, otherwise read `grace_period` from ControlMSettings
    - Implement `_escalate_immediately(rule, context, db)`: call TriggerFileWriter, update EscalationState to 'escalated', write EscalationLog entry
    - Implement `_start_grace_period(rule, context, db)`: create asyncio.Task with sleep + escalation, store in `_pending_tasks`, update EscalationState to 'pending'
    - Implement `_on_grace_period_expired(rule_id)`: write trigger file, update state to 'escalated', log event
    - Implement `_cancel_pending(rule_id, reason, db)`: cancel asyncio.Task, remove from dict, update state to 'idle', log event
    - Implement `handle_recovery(rule, db)`: if state is 'escalated' write recovery file + reset to idle; if 'pending' cancel timer + reset to idle
    - Implement `acknowledge(rule_id, username, db)`: validate rule has pending state, cancel task, log acknowledgment; reject if already escalated or idle
    - Implement `get_escalation_status(rule_id, db)` and `get_all_statuses(db)`: read from EscalationState, calculate grace_remaining_seconds for pending states
    - Implement `restore_state_on_startup()`: load pending states from DB, restart tasks for remaining time or escalate immediately if expired
    - Add `CRITICAL_PATTERNS` list for auto-defaulting critical flag
    - Instantiate module-level singleton: `escalation_service = EscalationService()`
    - _Requirements: 1.1, 2.4, 2.6, 2.10, 2.11, 3.1-3.10, 4.1-4.5_

  - [ ]* 3.2 Write property tests for escalation decision logic
    - **Property 1: Escalation Decision Correctness**
    - **Property 6: Critical Flag Overrides Grace Period**
    - **Property 7: Critical Flag Default from Pattern Matching**
    - **Property 11: One Active Escalation Per Rule**
    - Add to `tests/test_controlm_escalation.py`
    - _Validates: Requirements 1.1, 2.4, 2.6, 2.10, 2.11, 3.1-3.3, 3.10, 4.3_

  - [ ]* 3.3 Write property tests for acknowledgment and state persistence
    - **Property 9: Cancellation of Pending Escalation**
    - **Property 10: Acknowledgment Rejection When Not Applicable**
    - **Property 12: Escalation State Persistence Round-Trip**
    - Add to `tests/test_controlm_escalation.py`
    - _Validates: Requirements 3.4, 3.7, 3.9, 4.4_

- [x] 4. Checkpoint — Verify backend logic
  - Run `python -m pytest tests/test_controlm_escalation.py -v --tb=short` (if test file exists)
  - Run `python -c "import ast; ast.parse(open('app/services/controlm_escalation_service.py').read()); print('OK')"` for syntax check
  - Ensure imports resolve correctly

- [x] 5. API router for escalation
  - [x] 5.1 Implement escalation router in app/routers/escalation.py
    - Create `app/routers/escalation.py` with `router = APIRouter(tags=["escalation"])`
    - `GET /escalation/settings` — admin only (Depends(get_current_user) + role check), returns ControlMSettings row
    - `PUT /escalation/settings` — admin only, validates landing_zone (1-500 chars), grace_period (int 0-86400), controlm_enabled (bool), persists to DB
    - `POST /escalation/acknowledge/{rule_id}` — admin/viewer, calls `escalation_service.acknowledge()`
    - `GET /escalation/status` — admin/viewer, returns all rule escalation statuses
    - `GET /escalation/status/{rule_id}` — admin/viewer, returns single rule status
    - `GET /escalation/history` — admin/viewer, query params: rule_name, start_date, end_date, limit (max 1000)
    - Register router in `app/main.py`
    - _Requirements: 2.1, 2.2, 2.5-2.9, 3.4, 3.9, 5.4, 6.1-6.5_

  - [ ]* 5.2 Write property tests for settings validation and auth enforcement
    - **Property 4: Settings Input Validation**
    - **Property 5: Settings Persistence Round-Trip**
    - **Property 8: Authorization Enforcement**
    - _Validates: Requirements 2.1, 2.2, 2.5, 2.7, 2.8, 2.9_

  - [ ]* 5.3 Write property tests for audit history query and log creation
    - **Property 14: Audit Log Creation**
    - **Property 15: Audit History Query Correctness**
    - _Validates: Requirements 5.1-5.6_

- [x] 6. Integration into BackgroundScheduler
  - [x] 6.1 Wire EscalationService into BackgroundScheduler and app startup
    - In `background_scheduler.py` `_evaluate_rule()`: after `trigger_alert()` call, add `await escalation_service.handle_alert_triggered(rule, context, db)`
    - In `_evaluate_rule()` recovery paths: after `check_recovery()`, add `await escalation_service.handle_recovery(rule, db)`
    - In `app/main.py` lifespan startup: call `await escalation_service.restore_state_on_startup()` after scheduler starts
    - Update `notification_service.py` `create_rule()`: apply CRITICAL_PATTERNS auto-default on rule creation when route_name/route_id matches
    - Add `notify_controlm` and `critical` fields to `AlertRuleCreate` and `AlertRuleUpdate` schemas in `app/schemas/notifications.py`
    - _Requirements: 1.1, 2.3, 2.10, 2.11, 3.1, 3.10, 4.4_

- [x] 7. Checkpoint — Verify full backend integration
  - Run existing test suite: `python -m pytest tests/ -v --tb=short`
  - Verify new router is accessible: check `app/main.py` includes the escalation router
  - Syntax check all new files

- [x] 8. Frontend — Settings panel for ControlM escalation
  - [x] 8.1 Add ControlM Escalation section to Settings page
    - Add a "ControlM Escalation" card/section in `src/pages/Settings.jsx` (admin only visibility)
    - Fields: Global Enable toggle, Landing Zone path (text input, 1-500 chars), Grace Period seconds (number input, 0-86400)
    - Load current values from `GET /escalation/settings` when settings page mounts
    - Save via `PUT /escalation/settings` with validation feedback
    - Show success/error notification on save (use existing notification pattern)
    - _Requirements: 2.1, 2.2, 2.5, 2.6, 2.8, 2.9_

- [x] 9. Frontend — Alert rule form additions
  - [x] 9.1 Add notify_controlm and critical toggles to alert rule create/edit form
    - Add "ControlM Escalation" section in the alert rule create/edit form (likely in Notifications page)
    - Add `notify_controlm` toggle (default: off for new rules)
    - Add `critical` flag toggle (auto-checked based on CRITICAL_PATTERNS when route_name/route_id matches)
    - Include fields in create/update API payloads
    - _Requirements: 2.3, 2.10, 2.11_

- [ ] 10. Frontend — Escalation status indicators and acknowledge
  - [x] 10.1 Create EscalationBadge component and add to Notifications page
    - Create `src/components/EscalationBadge.jsx` — color-coded badge component
    - Fetch escalation statuses from `GET /escalation/status` on page mount and auto-refresh
    - Display alongside each alert rule row:
      - 🟡 Yellow pulsing: "Pending Escalation" with MM:SS countdown
      - 🔴 Red solid: "Escalated"
      - 🔴 Red + ⚡: "Escalated (Critical)"
      - No badge: idle or notify_controlm disabled
    - Add "Acknowledge" button for rules in pending state (non-critical, grace > 0)
    - Wire acknowledge button to `POST /escalation/acknowledge/{rule_id}`, refresh on success
    - Format remaining seconds as MM:SS (zero-padded)
    - _Requirements: 3.4, 3.6, 3.8, 6.1-6.5_

  - [ ]* 10.2 Write property test for MM:SS formatting
    - **Property 17: Remaining Time MM:SS Formatting**
    - _Validates: Requirements 6.2_

- [x] 11. Frontend — Escalation history view
  - [x] 11.1 Create EscalationHistory component
    - Create `src/components/EscalationHistory.jsx` or add section to Notifications page
    - Display table: Timestamp, Rule, Event Type, Details, User
    - Add filters: Rule name text input, start/end date pickers
    - Fetch from `GET /escalation/history` with query params
    - Max 1000 rows, sorted by timestamp descending
    - _Requirements: 5.4_

- [x] 12. Final checkpoint — Full verification
  - Run full backend test suite: `python -m pytest tests/ -v --tb=short`
  - Run frontend build: `npx vite build` (ensure no compilation errors)
  - Syntax check all new backend files
  - Verify all new API endpoints respond correctly

## Notes

- Tasks marked with `*` are optional property-based tests (can be skipped for faster MVP)
- All backend code follows existing patterns: SQLAlchemy models, service classes, FastAPI routers
- Frontend uses React (Vite), Zustand, Tailwind CSS, Axios — consistent with existing pages
- Tests use pytest + hypothesis (already in the project)
- The feature integrates into the existing BackgroundScheduler evaluation cycle (no new background process)
- asyncio.Lock is used instead of threading.Lock (single event loop architecture)
- Changes apply to PROD/ first, then promote to UAT/ following the standard workflow

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "3.3"] },
    { "id": 3, "tasks": ["5.1", "6.1"] },
    { "id": 4, "tasks": ["5.2", "5.3"] },
    { "id": 5, "tasks": ["8.1", "9.1", "10.1", "11.1"] },
    { "id": 6, "tasks": ["10.2"] }
  ]
}
```
