# Implementation Plan: Dashboard Version Check and SSL Upload

## Overview

This plan implements two features for the CRO IT APISIX Dashboard: (1) a background version check service that compares the running APISIX version against the latest GitHub release and displays an alert, and (2) an SSL certificate file upload mechanism. The implementation follows the existing FastAPI + React architecture, building incrementally from data models through services to UI components.

## Tasks

- [x] 1. Set up data models and configuration
  - [x] 1.1 Create the VersionCheckResult SQLAlchemy model
    - Create `backend/app/models/version_check.py` with the `VersionCheckResult` model
    - Fields: id, running_version, latest_version, update_available, check_timestamp, check_successful, error_message
    - Register the model import in `backend/app/main.py` lifespan so the table is created at startup
    - _Requirements: 3.3, 4.4_

  - [x] 1.2 Add version check configuration settings
    - Add `GITHUB_API_TIMEOUT`, `GITHUB_PROXY_URL`, and `VERSION_CHECK_INTERVAL_HOURS` to `backend/app/config.py` Settings class
    - Add Pydantic `field_validator` decorators to clamp out-of-range values to defaults and log warnings
    - GITHUB_API_TIMEOUT: int, default 10, valid range [1, 120]
    - GITHUB_PROXY_URL: str, default "", must be empty or valid http(s):// URL
    - VERSION_CHECK_INTERVAL_HOURS: int, default 24, valid range [1, 168]
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 1.3 Write property test for configuration range validation
    - **Property 4: Configuration range validation**
    - Test that in-range values are accepted as-is and out-of-range values fall back to defaults
    - Create `backend/tests/test_properties_config.py` using Hypothesis
    - Use `@given(st.integers())` to generate arbitrary integer values for timeout and interval
    - Minimum 100 iterations
    - **Validates: Requirements 5.1, 5.3, 5.4**

  - [x] 1.4 Create Pydantic response schemas
    - Create `backend/app/schemas/version_check.py` with `VersionCheckResponse` schema
    - Create `backend/app/schemas/ssl_upload.py` with `SSLUploadResponse` schema
    - _Requirements: 4.4, 7.3_

- [x] 2. Implement Version Check Service
  - [x] 2.1 Create the VersionCheckService class
    - Create `backend/app/services/version_check_service.py`
    - Implement `parse_semver(version_str)` — parse version string to (major, minor, patch) tuple, stripping pre-release/build suffixes
    - Implement `compare_versions(running, latest)` — return True if latest > running using semver ordering
    - Implement `get_running_version()` — query APISIX Admin API with configured timeout
    - Implement `get_latest_release()` — query GitHub Releases API, filter out pre-release/draft, retry 3 times with 5s spacing
    - Implement `run_check()` — orchestrate full check cycle, persist result to DB
    - Implement `get_latest_result()` — retrieve most recent result from DB
    - Support `GITHUB_PROXY_URL` for outbound GitHub requests
    - Handle all error scenarios: unreachable APIs, unparseable versions, DB write failures
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 2.2 Write property test for semantic version parsing
    - **Property 1: Semantic version parsing extracts correct components**
    - Create `backend/tests/test_properties_version.py` using Hypothesis
    - Generate arbitrary (major, minor, patch) tuples and optional pre-release suffixes
    - Verify parse_semver returns the correct tuple for valid inputs
    - Verify parse_semver returns None for invalid inputs
    - Minimum 100 iterations
    - **Validates: Requirements 1.3, 2.4**

  - [ ]* 2.3 Write property test for release filtering
    - **Property 2: Release filtering excludes pre-release and draft releases**
    - Add to `backend/tests/test_properties_version.py`
    - Generate lists of release objects with mixed stable/pre-release/draft flags
    - Verify the filtering logic never selects a pre-release or draft release
    - Minimum 100 iterations
    - **Validates: Requirements 2.2, 2.5**

  - [ ]* 2.4 Write property test for version comparison
    - **Property 3: Version comparison correctness**
    - Add to `backend/tests/test_properties_version.py`
    - Generate pairs of (major, minor, patch) tuples
    - Verify compare_versions returns True iff latest is strictly greater than running
    - Minimum 100 iterations
    - **Validates: Requirements 4.2, 4.3**

- [x] 3. Integrate version check into Background Scheduler
  - [x] 3.1 Add version check task to BackgroundScheduler
    - Modify `backend/app/services/background_scheduler.py` to import and run `VersionCheckService.run_check()`
    - Execute initial check within 60 seconds of startup
    - Schedule recurring checks at `VERSION_CHECK_INTERVAL_HOURS` interval
    - Implement retry logic: retry after 1 hour on failure, max 3 retries per cycle
    - Ensure version check runs independently of SMTP configuration (unlike notification scheduler)
    - _Requirements: 3.1, 3.2, 3.4, 3.5_

- [x] 4. Implement version check API endpoints
  - [x] 4.1 Add version check endpoints to system router
    - Add `GET /api/system/version-check` to `backend/app/routers/system.py`
    - Returns VersionCheckResponse with running_version, latest_version, update_available, last_checked, check_successful, error_message
    - Add `POST /api/system/version-check/trigger` for manual trigger (admin only)
    - Both endpoints require authentication via `get_current_user` dependency
    - _Requirements: 4.1, 4.4_

- [x] 5. Checkpoint - Backend version check complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement SSL file upload backend
  - [x] 6.1 Create SSL upload router
    - Create `backend/app/routers/ssl_upload.py`
    - Implement `POST /api/ssl/upload` endpoint accepting multipart form data
    - Accept optional `cert_file` (UploadFile), optional `key_file` (UploadFile), and `snis` (Form string)
    - Validate at least one file is provided (422 if neither)
    - Validate file extensions: only `.pem`, `.crt`, `.cer`, `.key` allowed (422 otherwise)
    - Validate file size: reject files > 1 MB with 413 status
    - Decode file content as UTF-8 (422 if decode fails)
    - Validate PEM content using existing validation functions
    - Forward validated content to APISIX Admin API via proxy_service
    - Parse snis string into array for the APISIX payload
    - Register router in `backend/app/main.py`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 6.2 Write property test for PEM validation
    - **Property 5: PEM validation accepts valid and rejects invalid content**
    - Create `backend/tests/test_properties_ssl.py` using Hypothesis
    - Generate strings with and without proper PEM delimiters
    - Verify validate_pem_cert returns True only for properly delimited certificate blocks
    - Verify validate_pem_key returns True only for properly delimited private key blocks
    - Minimum 100 iterations
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5**

  - [ ]* 6.3 Write property test for file extension validation
    - **Property 6: File extension validation**
    - Add to `backend/tests/test_properties_ssl.py`
    - Generate arbitrary filename strings with various extensions
    - Verify only .pem, .crt, .cer, .key (case-insensitive) are accepted
    - Minimum 100 iterations
    - **Validates: Requirements 6.6**

  - [ ]* 6.4 Write property test for file size validation
    - **Property 7: File size validation boundary**
    - Add to `backend/tests/test_properties_ssl.py`
    - Generate file sizes around the 1 MB boundary (1,048,576 bytes)
    - Verify files > 1 MB are rejected and files <= 1 MB are accepted
    - Minimum 100 iterations
    - **Validates: Requirements 6.7**

- [x] 7. Checkpoint - Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement frontend VersionBanner component
  - [x] 8.1 Create VersionBanner component
    - Create `frontend/src/components/VersionBanner.jsx`
    - Display update-available alert with running version, latest version, and last-checked date
    - Display up-to-date confirmation when versions match
    - Display warning state when check failed (show cached data with staleness indicator)
    - Display unavailable state when no prior data exists
    - _Requirements: 4.2, 4.3, 4.5, 4.6_

  - [x] 8.2 Integrate VersionBanner into SystemInfo page
    - Update `frontend/src/pages/SystemInfo.jsx` to fetch `/api/system/version-check` on mount
    - Render VersionBanner with the response data
    - Display result within 5 seconds of page load
    - _Requirements: 4.1_

  - [ ]* 8.3 Write component tests for VersionBanner
    - Create `frontend/src/components/VersionBanner.test.jsx` using Vitest + Testing Library
    - Test update-available state renders version numbers and date
    - Test up-to-date state renders confirmation message
    - Test error/stale state renders warning
    - Test unavailable state renders appropriate message
    - _Requirements: 4.2, 4.3, 4.5, 4.6_

- [x] 9. Implement frontend FileUploadField component
  - [x] 9.1 Create FileUploadField component
    - Create `frontend/src/components/FileUploadField.jsx`
    - File picker restricted to `.pem`, `.crt`, `.cer`, `.key` via accept attribute
    - Display selected filename and formatted file size
    - Implement `formatFileSize` utility function (bytes/KB/MB formatting)
    - Show remove button to clear selection
    - Client-side 1 MB size validation with error message
    - _Requirements: 8.1, 8.2, 8.3, 8.5, 8.7, 8.8_

  - [ ]* 9.2 Write property test for file size formatting
    - **Property 8: File size formatting**
    - Create `frontend/src/components/__tests__/test_properties_formatting.test.js` using fast-check
    - Generate non-negative integers representing file sizes
    - Verify: < 1024 → "{n} bytes", [1024, 1048576) → "{n/1024} KB" (1 decimal), >= 1048576 → "{n/1048576} MB" (1 decimal)
    - Minimum 100 iterations
    - **Validates: Requirements 8.2, 8.3**

  - [ ]* 9.3 Write component tests for FileUploadField
    - Create `frontend/src/components/FileUploadField.test.jsx` using Vitest + Testing Library
    - Test file selection displays filename and size
    - Test remove button clears selection
    - Test oversized file shows error and prevents submission
    - Test file picker only accepts allowed extensions
    - _Requirements: 8.1, 8.2, 8.5, 8.7, 8.8_

- [x] 10. Integrate file upload into SSL page
  - [x] 10.1 Update SSL page with file upload support
    - Modify `frontend/src/pages/SSL.jsx` to include FileUploadField components
    - Add mode toggle (file upload vs text paste) for certificate and key fields independently
    - On submit: if file mode, send multipart form to `/api/ssl/upload`; if paste mode, use existing flow
    - Display server-side validation errors adjacent to file inputs
    - _Requirements: 8.1, 8.4, 8.6_

  - [ ]* 10.2 Write integration tests for SSL page
    - Create or update `frontend/src/pages/SSL.test.jsx` using Vitest + Testing Library
    - Test mode toggle between file upload and text paste
    - Test file upload submission flow with mocked API
    - Test error display from server validation
    - _Requirements: 8.4, 8.6_

- [ ] 11. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (8 properties total)
- Unit tests validate specific examples and edge cases
- Backend uses Python (FastAPI, SQLAlchemy, Hypothesis for PBT)
- Frontend uses JavaScript/React (Vitest, Testing Library, fast-check for PBT)
- The version check scheduler runs independently of the existing notification scheduler's SMTP requirement

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.4"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["6.1", "8.1", "9.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "6.4", "8.2", "9.2", "9.3"] },
    { "id": 6, "tasks": ["8.3", "10.1"] },
    { "id": 7, "tasks": ["10.2"] }
  ]
}
```
