# Implementation Plan: Delete User Management

## Overview

Add a DELETE endpoint to the users router, integrate with the audit logging system, and add a Delete button with confirmation dialog to the Settings page user table. The implementation builds on existing patterns in `users.py`, `audit_service.py`, `ConfirmDialog.jsx`, and `Settings.jsx`.

## Tasks

- [ ] 1. Implement backend DELETE endpoint with guard logic
  - [x] 1.1 Add DELETE /users/{username} endpoint to `PROD/backend/app/routers/users.py`
    - Add username regex validation (`^[a-zA-Z0-9._-]{1,128}$`) using a Path parameter with regex constraint
    - Implement guard logic in order: admin role check (403), format validation (400), self-delete check (400), user existence check (404), last admin check (400)
    - On success: delete user from DB and return HTTP 200 with `{"message": "User '{username}' deleted successfully"}`
    - Accept `Request` dependency to extract client IP for audit logging
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 1.2 Integrate audit logging into the delete endpoint
    - On successful deletion: inline-create an `AuditLog` entry (action="DELETE", resource_type="users", resource_id=target username, status="success") and commit atomically with the user deletion in a single transaction
    - On guard rejection (self-delete, last admin, user not found, invalid format): log an audit entry with status="failed" and details containing the rejection reason, then raise the HTTPException
    - Ensure audit entry is persisted before the response is returned (single commit covers both audit + delete)
    - Import `AuditLog` model and `datetime`/`timezone` directly to avoid the auto-commit in `audit_service.log_action`
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 2. Checkpoint - Verify backend logic
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Add Delete button and confirmation flow to Settings UI
  - [x] 3.1 Add `disabled` prop support to `ConfirmDialog` component
    - In `PROD/frontend/src/components/ConfirmDialog.jsx`, add a `disabled` boolean prop (default `false`)
    - When `disabled` is true: confirm button shows a spinner SVG, is visually disabled (`opacity-50 cursor-not-allowed`), and `onClick` is suppressed
    - _Requirements: 4.5_

  - [x] 3.2 Add delete state, handler, and UI to `PROD/frontend/src/pages/Settings.jsx`
    - Add state: `deleteTarget` (username string or null), `deleting` (boolean)
    - Add `handleDeleteUser(username)` async function: calls `apiClient.delete(\`/users/${username}\`, { timeout: 30000 })`, refreshes user list on success, handles timeout (`err.code === 'ECONNABORTED'`) and API error responses
    - On success: set green success message `"User '{username}' deleted successfully"` that auto-dismisses after 5 seconds via `setTimeout`
    - On error: set red error message from `err.response?.data?.detail` or fallback generic text; error persists until manually dismissed (add a close button to the error notification)
    - Render a red "Delete" button in the actions column for each user where `user.username !== currentUsername`
    - Wire `ConfirmDialog` with title "Delete User", message "Are you sure you want to permanently delete user '{deleteTarget}'? This action cannot be undone.", variant "danger", confirmLabel "Delete", and `disabled={deleting}`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 4. Checkpoint - Verify frontend and backend integration
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Write property-based tests for delete endpoint
  - [ ]* 5.1 Write property test: Successful delete removes user and records audit
    - **Property 1: Successful delete removes user and records audit**
    - Use Hypothesis to generate random valid usernames and roles for target users
    - Verify: HTTP 200 returned, user no longer in DB, audit log entry exists with action="DELETE", status="success", correct actor
    - **Validates: Requirements 1.1, 2.1, 2.3**

  - [ ]* 5.2 Write property test: Non-admin users are always rejected
    - **Property 2: Non-admin users are always rejected**
    - Use Hypothesis to generate random viewer users and random target usernames
    - Verify: HTTP 403 returned with "Admin access required" regardless of target existence
    - **Validates: Requirements 1.2**

  - [ ]* 5.3 Write property test: Non-existent usernames return 404
    - **Property 3: Non-existent usernames return 404**
    - Use Hypothesis to generate random valid-format usernames not seeded in DB
    - Verify: HTTP 404 returned with "User '{username}' not found"
    - **Validates: Requirements 1.3**

  - [ ]* 5.4 Write property test: Self-deletion is always rejected
    - **Property 4: Self-deletion is always rejected**
    - Use Hypothesis to generate random admin usernames
    - Verify: HTTP 400 returned with "Cannot delete your own account"
    - **Validates: Requirements 1.4**

  - [ ]* 5.5 Write property test: Last admin protection
    - **Property 5: Last admin protection**
    - Set up single-admin scenario; attempt delete from a viewer-promoted-to-admin or use a second admin as caller
    - Verify: HTTP 400 returned with "Cannot delete the last admin user"
    - **Validates: Requirements 1.5**

  - [ ]* 5.6 Write property test: Invalid username format rejection
    - **Property 6: Invalid username format rejection**
    - Use Hypothesis to generate strings with special chars (`@`, `!`, spaces, etc.) and strings exceeding 128 chars
    - Verify: HTTP 400 returned with error message indicating invalid username format
    - **Validates: Requirements 1.6**

  - [ ]* 5.7 Write property test: All guard rejections produce failed audit entries
    - **Property 7: All guard rejections produce failed audit entries**
    - Use Hypothesis with `@given(st.sampled_from([...]))` for each rejection scenario
    - Verify: audit log entry exists with status="failed" and correct details for each rejection
    - **Validates: Requirements 2.2, 2.3**

- [ ] 6. Write unit tests for delete endpoint
  - [ ]* 6.1 Write unit tests in `PROD/backend/tests/test_delete_user.py`
    - Test successful deletion of a viewer user by an admin
    - Test successful deletion of an admin user (when multiple admins exist)
    - Test 403 when viewer attempts to delete
    - Test 404 for non-existent username
    - Test 400 for self-deletion
    - Test 400 for last admin protection
    - Test 400 for invalid username format (special chars, >128 chars)
    - Test audit log entries are created for success and failure scenarios
    - Test that deleted user's subsequent requests return 401 (implicit session invalidation)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The design uses implicit session invalidation — no token blacklist needed. Deleting the user row means `get_current_user` returns 401 on their next request.
- Audit logging is inlined (not via `audit_service.log_action`) to maintain transactional atomicity — audit entry and user delete share a single `db.commit()`
- The `ConfirmDialog` component already supports `variant="danger"` — only the `disabled` prop is new
- Property tests use the existing `hypothesis` library and follow the pattern in `test_auth_properties.py`
- Test file: `PROD/backend/tests/test_delete_user_properties.py` for PBT, `PROD/backend/tests/test_delete_user.py` for unit tests
- Run tests with: `cd PROD/backend && python -m pytest tests/ -v --tb=short`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "3.1"] },
    { "id": 2, "tasks": ["3.2"] },
    { "id": 3, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "6.1"] }
  ]
}
```
