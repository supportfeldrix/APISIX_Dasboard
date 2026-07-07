# Requirements Document

## Introduction

Add a "Delete User" capability to the Settings tab of the APISIX Dashboard (PROD environment). Currently, administrators can create users, toggle active status, and change roles, but cannot permanently remove user accounts from the system. This feature enables admins to delete users directly from the user management table, with appropriate safety guards to prevent destructive mistakes.

## Glossary

- **Dashboard**: The APISIX Dashboard web application (React frontend + FastAPI backend)
- **Admin**: A user with role `admin` who has full access to the Settings tab and user management
- **Settings_Tab**: The admin-only page in the Dashboard that displays and manages user accounts
- **Users_API**: The FastAPI router handling user management endpoints at `/users`
- **Confirm_Dialog**: The existing accessible modal component used for destructive action confirmations
- **Audit_Log**: The system that records all user actions (CREATE, DELETE, ROLE_CHANGE, etc.) for compliance
- **Current_User**: The admin user who is currently authenticated and performing the delete action

## Requirements

### Requirement 1: Delete User API Endpoint

**User Story:** As an admin, I want a backend API endpoint to delete a user account, so that I can permanently remove users who no longer need access to the dashboard.

#### Acceptance Criteria

1. WHEN an admin sends a DELETE request to `/users/{username}`, THE Users_API SHALL permanently remove the user record from the database, invalidate any active sessions belonging to the deleted user, and return HTTP 200 with a response body containing a confirmation message indicating which username was deleted
2. IF a non-admin user sends a DELETE request to `/users/{username}`, THEN THE Users_API SHALL reject the request with HTTP 403 and the message "Admin access required"
3. IF the target username does not exist in the database, THEN THE Users_API SHALL return HTTP 404 with the message "User '{username}' not found"
4. IF the admin attempts to delete their own account, THEN THE Users_API SHALL reject the request with HTTP 400 and the message "Cannot delete your own account"
5. IF the target user is the only remaining user with the admin role in the system, THEN THE Users_API SHALL reject the request with HTTP 400 and the message "Cannot delete the last admin user"
6. IF the `{username}` path parameter contains characters other than alphanumeric characters, hyphens, underscores, or periods, or exceeds 128 characters in length, THEN THE Users_API SHALL return HTTP 400 with an error message indicating invalid username format

### Requirement 2: Audit Logging for User Deletion

**User Story:** As a compliance officer, I want user deletions to be recorded in the audit log, so that there is a traceable history of account removals.

#### Acceptance Criteria

1. WHEN a user is successfully deleted, THE Audit_Log SHALL record an entry with action "DELETE", resource_type "users", resource_id set to the deleted username, the Current_User's username as the actor, and status "success"
2. WHEN a delete request is rejected due to a guard condition, THE Audit_Log SHALL record an entry with action "DELETE", resource_type "users", resource_id set to the target username, status "failed", the Current_User's username as the actor, and details containing the rejection reason
3. THE Audit_Log SHALL record the entry with a UTC timestamp before the delete response is returned to the caller, so that no successful or failed deletion can occur without a corresponding audit record

### Requirement 3: Delete Button in Settings Tab UI

**User Story:** As an admin, I want a "Delete" button on each user row in the Settings tab, so that I can initiate user removal from the management interface.

#### Acceptance Criteria

1. THE Settings_Tab SHALL display a "Delete" button in the actions column for each user row where the user is not the Current_User
2. THE Settings_Tab SHALL NOT display a "Delete" button on the row representing the Current_User
3. WHEN the admin clicks the "Delete" button, THE Settings_Tab SHALL display the Confirm_Dialog before executing the deletion
4. THE Confirm_Dialog SHALL display the title "Delete User", the message "Are you sure you want to permanently delete user '{username}'? This action cannot be undone.", and a red "Delete" confirmation button
5. WHEN the admin dismisses the Confirm_Dialog by clicking the backdrop or pressing Escape, THE Settings_Tab SHALL close the dialog without making any API call

### Requirement 4: Confirmation and Feedback

**User Story:** As an admin, I want to confirm before deleting and see clear feedback after the action, so that I do not accidentally remove users and I know the outcome of my action.

#### Acceptance Criteria

1. WHEN the admin confirms the deletion in the Confirm_Dialog, THE Settings_Tab SHALL send the DELETE request to the Users_API and, upon receiving an HTTP 2xx response, refresh the user list to reflect the removal within 2 seconds
2. WHEN the admin cancels the Confirm_Dialog, THE Settings_Tab SHALL close the dialog without making any API call and return focus to the user list
3. WHEN the deletion succeeds, THE Settings_Tab SHALL display a green success notification with the message "User '{username}' deleted successfully" that auto-dismisses after 5 seconds or can be manually dismissed by the admin
4. IF the deletion fails, THEN THE Settings_Tab SHALL display a red error notification showing the error detail returned by the Users_API response body, or a generic message indicating the deletion failed if no error detail is available, and the notification SHALL remain visible until manually dismissed by the admin
5. WHILE the delete request is in progress, THE Settings_Tab SHALL disable the confirm button and show a loading indicator to prevent duplicate submissions
6. IF the delete request does not receive a response within 30 seconds, THEN THE Settings_Tab SHALL abort the request, re-enable the confirm button, and display a red error notification indicating the request timed out
