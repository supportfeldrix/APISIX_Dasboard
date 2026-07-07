# Requirements Document

## Introduction

This document specifies requirements for two enhancements to the CRO IT APISIX Dashboard (PROD):

1. **APISIX Version Check with Alert** — A daily background job that compares the running APISIX Gateway version against the latest available release from the official Apache APISIX GitHub repository, and displays a prominent alert on the dashboard when an update is available.

2. **SSL Certificate File Upload** — An enhancement to the existing SSL management page that allows users to upload `.pem`, `.crt`, and `.key` files directly instead of pasting certificate content as text.

## Glossary

- **Dashboard**: The CRO IT APISIX Dashboard application (FastAPI backend + React frontend)
- **Version_Checker**: The backend service responsible for fetching and comparing APISIX release versions
- **Background_Scheduler**: The existing `BackgroundScheduler` class that runs periodic evaluation tasks within the FastAPI lifespan
- **APISIX_Admin_API**: The APISIX Gateway Admin API accessed via `APISIX_ADMIN_BASE_URL` with `APISIX_ADMIN_KEY`
- **GitHub_Releases_API**: The public GitHub API endpoint for Apache APISIX releases (`https://api.github.com/repos/apache/apisix/releases/latest`)
- **SSL_Uploader**: The backend endpoint responsible for reading uploaded SSL certificate and key files
- **System_Info_Page**: The frontend page that displays system information, dependencies, and changelog
- **SSL_Page**: The frontend page for managing APISIX SSL certificates
- **Notification_Banner**: A persistent UI alert component displayed prominently on the dashboard

## Requirements

### Requirement 1: Fetch Running APISIX Version

**User Story:** As a dashboard administrator, I want the system to detect the currently running APISIX Gateway version, so that the version check can compare it against the latest release.

#### Acceptance Criteria

1. WHEN the Version_Checker runs, THE Version_Checker SHALL query the APISIX_Admin_API using the configured APISIX_ADMIN_BASE_URL and APISIX_ADMIN_KEY, with a response timeout of 10 seconds, to retrieve the running APISIX Gateway version
2. IF the APISIX_Admin_API is unreachable or returns an error, THEN THE Version_Checker SHALL log the failure including a timestamp and error reason, and retain the last known version if one exists, or report the version as "unknown" if no previous version has been retrieved
3. WHEN the Version_Checker receives a version response from the APISIX_Admin_API, THE Version_Checker SHALL parse the version string into a comparable semantic version format (major.minor.patch), stripping any pre-release or build-metadata suffixes
4. IF the version string returned by the APISIX_Admin_API cannot be parsed into semantic version format, THEN THE Version_Checker SHALL log an error message indicating the unparseable value and report the version as "unknown"

### Requirement 2: Fetch Latest Available APISIX Release

**User Story:** As a dashboard administrator, I want the system to check the latest APISIX release from the official source, so that I am informed when a newer version is available.

#### Acceptance Criteria

1. WHEN the Version_Checker runs, THE Version_Checker SHALL query the GitHub_Releases_API to retrieve the latest stable APISIX release version within a timeout of 10 seconds per request attempt
2. WHEN the Version_Checker retrieves releases from the GitHub_Releases_API, THE Version_Checker SHALL exclude pre-release and draft releases from the latest version determination
3. IF the GitHub_Releases_API is unreachable or returns an error after 3 consecutive request attempts spaced 5 seconds apart, THEN THE Version_Checker SHALL log the failure including a timestamp and error description, and retain the last known latest version if one exists
4. WHEN the Version_Checker successfully retrieves a release tag, THE Version_Checker SHALL parse the tag into a comparable semantic version format (major.minor.patch)
5. IF a retrieved release tag does not conform to semantic versioning format (major.minor.patch), THEN THE Version_Checker SHALL skip that release, log a warning indicating the unparseable tag, and continue evaluation with the next most recent release
6. IF no valid non-pre-release, non-draft release with a parseable semantic version tag is found, THEN THE Version_Checker SHALL log a warning and retain the last known latest version if one exists, or indicate that no version information is available if no prior version was stored

### Requirement 3: Daily Version Comparison Schedule

**User Story:** As a dashboard administrator, I want the version check to run automatically once per day, so that I receive timely notifications about available updates without manual intervention.

#### Acceptance Criteria

1. THE Background_Scheduler SHALL execute the Version_Checker once every 24 hours, with a maximum allowable drift of 5 minutes between scheduled executions
2. WHEN the Dashboard backend starts, THE Background_Scheduler SHALL execute an initial version check within 60 seconds of startup
3. THE Version_Checker SHALL persist the comparison result (running version, latest version, check timestamp, update available flag) to the database, retaining only the most recent result per check cycle
4. IF a version check cycle fails, THEN THE Background_Scheduler SHALL retry the check after 1 hour, up to a maximum of 3 retry attempts before ceasing retries until the next scheduled 24-hour cycle
5. IF all retry attempts for a version check cycle are exhausted without success, THEN THE Version_Checker SHALL persist a result record with the check timestamp and a flag indicating the check failed

### Requirement 4: Version Update Alert Display

**User Story:** As a dashboard administrator, I want to see a prominent alert when my APISIX version is outdated, so that I can plan an upgrade.

#### Acceptance Criteria

1. WHEN the administrator navigates to the System_Info_Page, THE Dashboard SHALL perform a version check by comparing the running APISIX version against the latest available version using semantic versioning and display the result within 5 seconds of page load
2. WHEN the running APISIX version is older than the latest available version, THE Dashboard SHALL display a Notification_Banner on the System_Info_Page indicating a new version is available, including the current running version, the latest available version, and the date the check was last performed in ISO 8601 format (YYYY-MM-DD)
3. WHEN the running APISIX version matches or exceeds the latest available version, THE Dashboard SHALL display a confirmation message on the System_Info_Page stating the system is up to date, including the current version number and the date the check was last performed
4. THE Dashboard SHALL provide an API endpoint that returns the current version check status including: running version, latest version, a boolean update-available flag, and last-checked timestamp in ISO 8601 format
5. IF the version check fails due to the version source being unreachable or returning an invalid response, THEN THE Dashboard SHALL display the last successfully retrieved version data along with a warning indicating the check could not be completed and showing the age of the cached data
6. IF no prior version check data exists and the version source is unreachable, THEN THE Dashboard SHALL display a message indicating that version information is currently unavailable and the check should be retried later

### Requirement 5: Version Check Configuration

**User Story:** As a dashboard administrator, I want to configure the version check behaviour, so that I can adapt it to my environment's network constraints.

#### Acceptance Criteria

1. THE Dashboard SHALL read a configurable `GITHUB_API_TIMEOUT` setting from environment variables as an integer representing seconds, with a default of 10 and a valid range of 1 to 120, for the GitHub_Releases_API request timeout
2. WHERE a network proxy is required, THE Version_Checker SHALL support an optional `GITHUB_PROXY_URL` environment variable that accepts a valid HTTP or HTTPS URL for outbound requests to the GitHub_Releases_API
3. THE Dashboard SHALL read a configurable `VERSION_CHECK_INTERVAL_HOURS` setting from environment variables as an integer with a default of 24 and a valid range of 1 to 168, to control the check frequency
4. IF `GITHUB_API_TIMEOUT`, `VERSION_CHECK_INTERVAL_HOURS`, or `GITHUB_PROXY_URL` is set to a value outside its valid range or format, THEN THE Dashboard SHALL reject the value at startup and fall back to the default value for that setting while logging a warning message indicating the invalid configuration

### Requirement 6: SSL Certificate File Upload Endpoint

**User Story:** As a dashboard administrator, I want to upload SSL certificate and key files directly, so that I do not need to manually copy and paste PEM content.

#### Acceptance Criteria

1. THE SSL_Uploader SHALL accept multipart file uploads for a certificate file and a private key file, where each file may be provided independently or together in a single request
2. WHEN a certificate file is uploaded, THE SSL_Uploader SHALL read the file content and validate it as a valid PEM certificate using the existing `validate_pem_cert` function
3. WHEN a private key file is uploaded, THE SSL_Uploader SHALL read the file content and validate it as a valid PEM private key using the existing `validate_pem_key` function
4. IF the uploaded certificate file does not contain a valid PEM certificate, THEN THE SSL_Uploader SHALL return a 422 error with the message "Invalid PEM certificate format"
5. IF the uploaded private key file does not contain a valid PEM private key, THEN THE SSL_Uploader SHALL return a 422 error with the message "Invalid PEM private key format"
6. IF an uploaded file has an extension other than `.pem`, `.crt`, `.cer`, or `.key`, THEN THE SSL_Uploader SHALL return a 422 error with a message indicating the file extension is not allowed
7. IF an uploaded file exceeds 1 MB in size, THEN THE SSL_Uploader SHALL return a 413 error with the message "File size exceeds maximum allowed (1 MB)"
8. IF the request contains neither a certificate file nor a private key file, THEN THE SSL_Uploader SHALL return a 422 error with a message indicating that at least one file must be provided
9. THE SSL_Uploader SHALL decode uploaded file content as UTF-8 before performing PEM validation

### Requirement 7: SSL File Upload Integration with APISIX

**User Story:** As a dashboard administrator, I want uploaded SSL files to be submitted to APISIX the same way as pasted content, so that the upload method produces identical results.

#### Acceptance Criteria

1. WHEN valid certificate and key files are uploaded, THE SSL_Uploader SHALL extract the PEM text content and forward it to the APISIX_Admin_API in the same JSON payload format as the existing paste-based approach (fields: `cert`, `key`) using the same proxy_service `forward_request` function
2. WHEN `snis` values are provided alongside the file upload, THE SSL_Uploader SHALL include the `snis` field in the JSON payload as an array of one or more domain name strings (e.g., `["example.com", "*.example.com"]`)
3. WHEN the APISIX_Admin_API returns a success response (HTTP 2xx), THE SSL_Uploader SHALL return the APISIX response body and status code to the client
4. IF the APISIX_Admin_API returns an error response (HTTP 4xx or 5xx), THEN THE SSL_Uploader SHALL return the error status code and error message body from APISIX to the client without modification
5. IF the APISIX_Admin_API is unreachable or the request times out within the configured `APISIX_ADMIN_TIMEOUT` period (default 10 seconds), THEN THE SSL_Uploader SHALL return a 503 error with a message indicating the APISIX Admin API is unreachable

### Requirement 8: SSL File Upload UI

**User Story:** As a dashboard administrator, I want a file picker on the SSL page, so that I can browse and select certificate files from my local machine.

#### Acceptance Criteria

1. THE SSL_Page SHALL display a file upload option alongside the existing text paste fields for certificate and key
2. WHEN a user selects a certificate file via the file picker, THE SSL_Page SHALL display the selected filename and file size formatted in human-readable units (bytes for sizes under 1 KB, KB with one decimal place for sizes under 1 MB, MB with one decimal place for sizes 1 MB and above)
3. WHEN a user selects a key file via the file picker, THE SSL_Page SHALL display the selected filename and file size formatted in human-readable units (bytes for sizes under 1 KB, KB with one decimal place for sizes under 1 MB, MB with one decimal place for sizes 1 MB and above)
4. THE SSL_Page SHALL allow the user to choose either file upload or text paste for each field independently (certificate file upload with key paste, or vice versa)
5. IF a selected file exceeds 1 MB in size, THEN THE SSL_Page SHALL display an error message indicating the file exceeds the maximum allowed size and SHALL prevent submission until the file is removed or replaced
6. IF a file upload validation fails after submission, THEN THE SSL_Page SHALL display the error message returned by the SSL_Uploader adjacent to the file input
7. THE SSL_Page SHALL restrict the file picker to accept only `.pem`, `.crt`, `.cer`, and `.key` file extensions
8. WHEN a user has selected a file, THE SSL_Page SHALL display a control to remove the selected file and revert the field to its empty state
