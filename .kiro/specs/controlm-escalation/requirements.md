# Requirements Document

## Introduction

The ControlM Escalation feature adds automated phone-call escalation to the APISIX Dashboard. When an alert rule triggers (route health check failure, upstream error, JWT failure, or pod health issue) and the existing email notification is sent, the system writes a trigger file to a configurable network share (landing zone). ControlM's File Watcher detects this file and triggers a job that initiates a phone call to 1st call / standby IT members. Because the APISIX Dashboard monitors critical real-time screening and decisioning infrastructure for the bank (e.g., APISIX routes handling live transaction screening via Actimize), the default behavior is immediate escalation (0 second grace period). An optional grace period can be configured for non-critical alert rules where operators may acknowledge alerts before the trigger file is written.

## Glossary

- **Dashboard_App**: The APISIX Dashboard FastAPI application that manages routes, monitors health, evaluates alert rules, and sends notifications
- **Trigger_File**: A file written to the ControlM landing zone that signals ControlM to execute an escalation job
- **Landing_Zone**: A configurable network share path that ControlM File Watchers poll for trigger files
- **ControlM**: The enterprise job scheduling system (Control-M) that detects trigger files and executes escalation jobs (phone calls)
- **File_Watcher**: A ControlM task type that polls a directory at configurable intervals for new files matching a pattern
- **Grace_Period**: A configurable time window (in seconds) after an alert trigger during which an operator can acknowledge the alert to prevent ControlM escalation. Defaults to 0 (immediate escalation) for critical real-time infrastructure.
- **Critical_Rule**: An alert rule flagged as critical (e.g., real-time screening route health checks) that always escalates immediately with 0 grace period, regardless of the global grace period setting
- **Acknowledgment**: An explicit action by an operator in the dashboard indicating they are aware of and handling an alert (only applicable when grace period > 0)
- **Escalation**: The process of notifying 1st call / standby IT members via phone call through ControlM when an email alert goes unacknowledged
- **Alert_Rule**: An existing notification rule in the APISIX Dashboard that defines trigger conditions (JWT failure, upstream error, high error rate, health check failure, pod health)

## Requirements

### Requirement 1: ControlM Trigger File Generation

**User Story:** As an IT operations manager, I want the monitoring system to write a trigger file to the ControlM landing zone when an alert rule triggers, so that ControlM can initiate phone-call escalation to standby staff.

#### Acceptance Criteria

1. WHEN an alert rule triggers and the grace period expires without acknowledgment (or grace period is 0), THE Dashboard_App SHALL write a Trigger_File to the configured Landing_Zone path within 10 seconds of the alert trigger
2. THE Dashboard_App SHALL generate the Trigger_File name using the format `CROIT_ALERT_{rule_name}_{timestamp}.trigger` where timestamp is the UTC time of the alert in `YYYYMMDD_HHMMSS` format
3. THE Dashboard_App SHALL write the Trigger_File content as plain text with one key-value pair per line in the format `KEY=VALUE`, including the fields: rule_name, route_id, route_name, condition_type, failure_message (truncated to 500 characters if longer), alert_timestamp (ISO 8601 UTC format), and severity (CRITICAL or WARNING based on the rule's critical flag)
4. THE Dashboard_App SHALL write the Trigger_File atomically by first writing to a temporary file in the Landing_Zone and then renaming it to the final filename, so that the ControlM File Watcher does not detect a partial file
5. IF the Landing_Zone path is not reachable or not writable, THEN THE Dashboard_App SHALL log an error message indicating the path and failure reason, and continue normal alert evaluation without interruption
6. THE Dashboard_App SHALL sanitize the rule name in the Trigger_File filename by replacing non-alphanumeric characters (except underscores) with underscores and truncating the sanitized name to a maximum of 100 characters
7. IF the sanitized rule name results in an empty string, THEN THE Dashboard_App SHALL use the literal value `UNKNOWN` as the rule name in the Trigger_File filename

### Requirement 2: ControlM Escalation Configuration

**User Story:** As an administrator, I want to configure the ControlM escalation settings through the dashboard, so that I can control which alert rules escalate and where trigger files are written.

#### Acceptance Criteria

1. THE Dashboard_App SHALL provide a settings interface for configuring the Landing_Zone path, accepting a non-empty string between 1 and 500 characters
2. THE Dashboard_App SHALL provide a settings interface for configuring the Grace_Period duration in seconds with a default value of 0 seconds (immediate escalation), accepting an integer value between 0 and 86400
3. THE Dashboard_App SHALL provide a per-rule toggle named `notify_controlm` to enable or disable ControlM escalation for individual alert rules, defaulting to disabled for newly created rules
4. IF the `notify_controlm` toggle is disabled for an alert rule, THEN THE Dashboard_App SHALL not write a Trigger_File for that rule regardless of alert state
5. THE Dashboard_App SHALL persist all ControlM escalation settings in the application database
6. THE Dashboard_App SHALL provide a global toggle to enable or disable ControlM escalation for all rules; IF the global toggle is disabled, THEN THE Dashboard_App SHALL suppress all Trigger_File writes regardless of individual per-rule `notify_controlm` settings
7. IF a user without the admin role attempts to modify ControlM escalation settings, THEN THE Dashboard_App SHALL reject the request and return an error message indicating insufficient permissions
8. IF the Landing_Zone path is empty or exceeds 500 characters, THEN THE Dashboard_App SHALL reject the input and display an error message indicating the valid length range
9. IF the Grace_Period value is not an integer between 0 and 86400, THEN THE Dashboard_App SHALL reject the input and display an error message indicating the valid range
10. THE Dashboard_App SHALL provide a per-rule `critical` flag that, when enabled, forces the grace period to 0 for that rule regardless of the global grace period setting
11. THE Dashboard_App SHALL default the `critical` flag to enabled for alert rules whose route names or route IDs match known real-time screening patterns (e.g., RealTimeWSProvider, RTS)

### Requirement 3: Grace Period and Acknowledgment

**User Story:** As an on-call operator, I want the option to acknowledge alerts within a grace period for non-critical rules to prevent unnecessary phone-call escalation, while critical rules (real-time screening) escalate immediately without delay.

#### Acceptance Criteria

1. WHEN an alert rule triggers and `notify_controlm` is enabled, THE Dashboard_App SHALL evaluate the effective grace period: 0 seconds if the rule's `critical` flag is enabled, otherwise the configured Grace_Period value
2. IF the effective grace period is 0, THEN THE Dashboard_App SHALL write the Trigger_File to the Landing_Zone immediately upon alert trigger without waiting for acknowledgment
3. IF the effective grace period is greater than 0, THEN THE Dashboard_App SHALL start a Grace_Period countdown before writing the Trigger_File
4. WHEN an operator acknowledges an alert while the Grace_Period countdown is still active for that rule, THE Dashboard_App SHALL cancel the pending Trigger_File write, remove the pending escalation state for that rule, and display a confirmation indication on the dashboard within 2 seconds of the acknowledgment action
5. WHEN the Grace_Period expires without acknowledgment, THE Dashboard_App SHALL write the Trigger_File to the Landing_Zone within 5 seconds of expiry
6. THE Dashboard_App SHALL display an "Acknowledge" button on the dashboard for each alert rule that has triggered, has a pending escalation, and has a grace period greater than 0; THE Dashboard_App SHALL remove the button when the alert is acknowledged, recovers, or the Grace_Period expires
7. WHEN an alert rule recovers (condition returns to normal) during the Grace_Period, THE Dashboard_App SHALL cancel the pending Trigger_File write for that rule
8. WHILE a Grace_Period countdown is active for a rule, THE Dashboard_App SHALL display the remaining time on the dashboard updated at least every 5 seconds
9. IF an acknowledgment request is received for a rule whose Grace_Period has already expired or whose effective grace period is 0, THEN THE Dashboard_App SHALL reject the acknowledgment and indicate to the operator that escalation has already occurred
10. WHEN an alert rule triggers and a previous Grace_Period or escalation cycle for that rule has not yet been resolved by a recovery, THE Dashboard_App SHALL not start a new Grace_Period countdown (one active escalation cycle per rule at a time)

### Requirement 4: Trigger File Cleanup

**User Story:** As a system administrator, I want trigger files to be cleaned up after processing, so that stale files do not cause repeated ControlM escalations.

#### Acceptance Criteria

1. WHEN an alert rule recovers after a Trigger_File has been written for it, THE Dashboard_App SHALL write a recovery file named `CROIT_RECOVERY_{rule_name}_{timestamp}.trigger` to the Landing_Zone, where the rule name is sanitized using the same rules as Trigger_File names (non-alphanumeric characters except underscores replaced with underscores) and timestamp is in `YYYYMMDD_HHMMSS` format
2. THE Dashboard_App SHALL not delete previously written Trigger_Files from the Landing_Zone (ControlM manages file lifecycle after detection)
3. WHILE an alert rule remains triggered and a Trigger_File has already been written for it, THE Dashboard_App SHALL NOT write another Trigger_File for that rule until it recovers
4. THE Dashboard_App SHALL persist the escalation state (whether a Trigger_File has been written) for each alert rule in the application database so that duplicate prevention survives application restarts
5. IF the Landing_Zone is not reachable or not writable when writing a recovery file, THE Dashboard_App SHALL log an error message and retry the recovery file write on the next evaluation cycle

### Requirement 5: Escalation Audit Trail

**User Story:** As an IT operations manager, I want a log of all ControlM escalation events, so that I can review escalation history and verify the system is working correctly.

#### Acceptance Criteria

1. WHEN a Trigger_File is written to the Landing_Zone, THE Dashboard_App SHALL record the event in an escalation log table with event type "trigger_file_written", rule name, file path, and timestamp in ISO 8601 UTC format
2. WHEN an operator acknowledges an alert and cancels a pending escalation, THE Dashboard_App SHALL record the acknowledgment in the escalation log with event type "acknowledged", the operator username, rule name, and timestamp in ISO 8601 UTC format
3. WHEN a Grace_Period expires without acknowledgment, THE Dashboard_App SHALL record the expiry event in the escalation log with event type "grace_period_expired", rule name, and timestamp in ISO 8601 UTC format
4. THE Dashboard_App SHALL provide an API endpoint accessible to users with the admin or viewer role to retrieve escalation history filtered by rule name and date range, returning a maximum of 1000 records per response sorted by timestamp descending
5. WHEN a Trigger_File write fails due to an unreachable Landing_Zone, THE Dashboard_App SHALL record the failure in the escalation log with event type "trigger_file_failed", rule name, error message truncated to 500 characters, and timestamp in ISO 8601 UTC format
6. WHEN a recovery file is written to the Landing_Zone for a rule that recovers, THE Dashboard_App SHALL record the event in the escalation log with event type "recovery_file_written", rule name, file path, and timestamp in ISO 8601 UTC format

### Requirement 6: Escalation Status Visibility

**User Story:** As an on-call operator, I want to see the escalation status of each alert rule on the dashboard, so that I know which rules have pending or completed ControlM escalations.

#### Acceptance Criteria

1. THE Dashboard_App SHALL display an escalation status indicator alongside each alert rule on the notifications page for rules with `notify_controlm` enabled, showing one of the following states: no indicator (idle/recovered), "Pending Escalation", "Escalated", or "Escalated (Critical)"
2. WHILE a Grace_Period countdown is active for a non-critical rule, THE Dashboard_App SHALL display a "Pending Escalation" status with the remaining time shown in `MM:SS` format, updated on each dashboard auto-refresh cycle
3. WHEN a Trigger_File has been written for a rule that remains triggered, THE Dashboard_App SHALL display an "Escalated" status indicator; IF the rule has the `critical` flag enabled, THE indicator SHALL display "Escalated (Critical)"
4. WHEN a rule recovers, THE Dashboard_App SHALL remove the escalation status indicator (whether "Pending Escalation" or "Escalated") within the next dashboard auto-refresh cycle
5. IF `notify_controlm` is enabled for a rule but no Grace_Period is active and no Trigger_File has been written for the current alert incident, THEN THE Dashboard_App SHALL display no escalation status indicator for that rule
