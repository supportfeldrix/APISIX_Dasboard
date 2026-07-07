# Requirements Document

## Introduction

This document defines the requirements for a custom Apache APISIX management dashboard added as a new module to the existing Fircosoft Dashboard application. The dashboard replaces the default APISIX Dashboard UI and interacts exclusively with the APISIX Admin API via REST calls. It supports role-based access control, local authentication (with LDAP integration planned for Phase 2), and a monitoring tab that surfaces CPU and memory metrics from the existing Prometheus metrics endpoint. The module is designed to run locally on Windows first, then be deployed to OpenShift.

## Glossary

- **APISIX_Dashboard**: The new module/section added to the Fircosoft Dashboard application that manages Apache APISIX resources.
- **Admin_API**: The Apache APISIX Admin REST API (v3) used as the sole configuration interface.
- **Admin_API_Proxy**: The FastAPI backend service that proxies all Admin API calls, keeping credentials out of the browser.
- **Auth_Service**: The existing authentication service in the Fircosoft backend, extended to support APISIX Dashboard roles.
- **LDAP_Service**: The LDAP integration service used in Phase 2 for enterprise authentication.
- **Metrics_Service**: The backend service that fetches and parses Prometheus metrics from the APISIX metrics endpoint.
- **Route**: An APISIX routing rule that maps incoming requests to an upstream service.
- **Service**: An APISIX service object that groups upstream and plugin configurations.
- **Upstream**: An APISIX upstream object that defines backend server pools and load-balancing settings.
- **Consumer**: An APISIX consumer object representing an API client with associated credentials and plugins.
- **Plugin**: An APISIX plugin attached to a Route, Service, Consumer, Global Rule, or Plugin Metadata object.
- **SSL_Certificate**: A TLS certificate and key pair managed by APISIX for HTTPS termination.
- **Global_Rule**: An APISIX global rule that applies a plugin to every request.
- **Plugin_Metadata**: APISIX-level metadata configuration for a specific plugin.
- **Viewer**: A dashboard user with read-only access to all APISIX resources.
- **Admin**: A dashboard user with full read/write access to all APISIX resources.
- **Session**: A server-side or JWT-based authenticated session that grants access to the APISIX_Dashboard.
- **Prometheus_Metrics**: The text-format metrics exposed at the configured APISIX metrics endpoint, scraped by the Metrics_Service.

---

## Requirements

### Requirement 1: Local Authentication

**User Story:** As a DevOps user, I want to log in with a username and password, so that I can access the APISIX Dashboard securely during local development.

#### Acceptance Criteria

1. WHEN a user submits valid credentials (username and password) to the login endpoint, THE Auth_Service SHALL return a JWT access token with a configurable expiry (default 30 minutes).
2. WHEN a user submits invalid credentials, THE Auth_Service SHALL return an HTTP 401 response with a descriptive error message and SHALL NOT return a token.
3. THE Auth_Service SHALL store passwords as bcrypt hashes and SHALL NOT store or log plaintext passwords.
4. WHEN a valid JWT token is included in a request to a protected endpoint, THE Admin_API_Proxy SHALL process the request.
5. WHEN an expired or invalid JWT token is included in a request, THE Admin_API_Proxy SHALL return an HTTP 401 response.
6. WHEN a user calls the logout endpoint, THE Auth_Service SHALL invalidate the session token so that subsequent requests with that token are rejected.
7. THE Auth_Service SHALL seed a default local admin account with username `admin` and password `N03ntry#` on first startup if no admin account exists.

---

### Requirement 2: Role-Based Access Control

**User Story:** As a system administrator, I want to assign Viewer or Admin roles to users, so that I can control who can read versus modify APISIX configuration.

#### Acceptance Criteria

1. THE Auth_Service SHALL support exactly two APISIX Dashboard roles: `viewer` and `admin`.
2. WHILE a user holds the `viewer` role, THE APISIX_Dashboard SHALL permit only HTTP GET operations against all APISIX resource endpoints.
3. WHILE a user holds the `viewer` role, THE Admin_API_Proxy SHALL reject any non-GET request with an HTTP 403 response.
4. WHILE a user holds the `admin` role, THE APISIX_Dashboard SHALL permit full CRUD operations against all APISIX resource endpoints.
5. WHEN an unauthenticated request reaches any protected endpoint, THE Admin_API_Proxy SHALL return an HTTP 401 response before forwarding the request to the Admin_API.
6. THE Admin_API_Proxy SHALL NOT expose the Admin_API key or Admin_API base URL to the browser at any time.

---

### Requirement 3: Admin API Proxy

**User Story:** As a security-conscious operator, I want all Admin API calls to be proxied through the backend, so that API credentials are never exposed to the browser.

#### Acceptance Criteria

1. THE Admin_API_Proxy SHALL forward authenticated requests to the Admin_API using the configured Admin API key stored as a server-side environment variable.
2. WHEN the Admin_API returns a non-2xx response, THE Admin_API_Proxy SHALL forward the status code and error body to the caller without modification.
3. WHEN the Admin_API is unreachable, THE Admin_API_Proxy SHALL return an HTTP 503 response with a descriptive error message within 10 seconds.
4. THE Admin_API_Proxy SHALL validate that the request path targets only permitted APISIX resource types (routes, services, upstreams, consumers, plugins, ssl, global_rules, plugin_metadata) and SHALL return HTTP 400 for any other path.
5. THE Admin_API_Proxy SHALL log every proxied request including timestamp, authenticated username, HTTP method, resource path, and response status code.

---

### Requirement 4: Route Management

**User Story:** As a DevOps user, I want to create, view, update, enable, disable, and delete APISIX routes, so that I can manage API routing rules without accessing etcd directly.

#### Acceptance Criteria

1. WHEN a user requests the routes list, THE APISIX_Dashboard SHALL display all routes returned by the Admin_API including id, name, uri, methods, status, and upstream_id.
2. WHEN a user submits a new route definition in YAML or JSON format, THE Admin_API_Proxy SHALL validate the payload structure and forward a PUT request to the Admin_API routes endpoint.
3. IF the route payload fails schema validation, THEN THE Admin_API_Proxy SHALL return an HTTP 422 response with field-level error details before forwarding to the Admin_API.
4. WHEN a user enables a route, THE Admin_API_Proxy SHALL send a PATCH request setting `status` to `1` for that route id.
5. WHEN a user disables a route, THE Admin_API_Proxy SHALL send a PATCH request setting `status` to `0` for that route id.
6. WHEN a user deletes a route, THE Admin_API_Proxy SHALL send a DELETE request to the Admin_API and SHALL require explicit confirmation from the user before executing.
7. THE APISIX_Dashboard SHALL provide a YAML editor and a JSON editor toggle for route creation and editing, with syntax highlighting and inline validation.

---

### Requirement 5: Service Management

**User Story:** As a DevOps user, I want to perform full CRUD operations on APISIX services, so that I can manage shared upstream and plugin configurations.

#### Acceptance Criteria

1. WHEN a user requests the services list, THE APISIX_Dashboard SHALL display all services returned by the Admin_API including id, name, upstream_id, and plugin count.
2. WHEN a user submits a new or updated service definition, THE Admin_API_Proxy SHALL validate the payload and forward the request to the Admin_API services endpoint.
3. IF the service payload fails schema validation, THEN THE Admin_API_Proxy SHALL return an HTTP 422 response with field-level error details.
4. WHEN a user deletes a service, THE Admin_API_Proxy SHALL require explicit user confirmation before sending the DELETE request to the Admin_API.

---

### Requirement 6: Upstream Management

**User Story:** As a DevOps user, I want to perform full CRUD operations on APISIX upstreams, so that I can manage backend server pools and load-balancing configuration.

#### Acceptance Criteria

1. WHEN a user requests the upstreams list, THE APISIX_Dashboard SHALL display all upstreams returned by the Admin_API including id, name, type (load-balancing algorithm), and node count.
2. WHEN a user submits a new or updated upstream definition, THE Admin_API_Proxy SHALL validate the payload and forward the request to the Admin_API upstreams endpoint.
3. IF the upstream payload fails schema validation, THEN THE Admin_API_Proxy SHALL return an HTTP 422 response with field-level error details.
4. WHEN a user deletes an upstream, THE Admin_API_Proxy SHALL require explicit user confirmation before sending the DELETE request to the Admin_API.

---

### Requirement 7: Consumer Management

**User Story:** As a DevOps user, I want to perform full CRUD operations on APISIX consumers, so that I can manage API client identities and their associated credentials.

#### Acceptance Criteria

1. WHEN a user requests the consumers list, THE APISIX_Dashboard SHALL display all consumers returned by the Admin_API including username, plugins, and creation time.
2. WHEN a user submits a new or updated consumer definition, THE Admin_API_Proxy SHALL validate the payload and forward the request to the Admin_API consumers endpoint.
3. IF the consumer payload fails schema validation, THEN THE Admin_API_Proxy SHALL return an HTTP 422 response with field-level error details.
4. WHEN a user deletes a consumer, THE Admin_API_Proxy SHALL require explicit user confirmation before sending the DELETE request to the Admin_API.

---

### Requirement 8: Plugin and Policy Management

**User Story:** As a DevOps user, I want to manage plugins attached to routes, services, consumers, global rules, and plugin metadata, so that I can configure cross-cutting policies without editing raw configuration files.

#### Acceptance Criteria

1. WHEN a user views a Route, Service, or Consumer detail page, THE APISIX_Dashboard SHALL display the list of plugins currently attached to that resource with their configuration.
2. WHEN a user adds or updates a plugin on a resource, THE Admin_API_Proxy SHALL merge the plugin configuration into the resource payload and forward a PUT or PATCH request to the Admin_API.
3. WHEN a user removes a plugin from a resource, THE Admin_API_Proxy SHALL remove the plugin key from the resource payload and forward the updated resource to the Admin_API.
4. WHEN a user requests the global rules list, THE APISIX_Dashboard SHALL display all global rules returned by the Admin_API.
5. WHEN a user requests the plugin metadata list, THE APISIX_Dashboard SHALL display all plugin metadata entries returned by the Admin_API.
6. WHEN a user updates global rules or plugin metadata, THE Admin_API_Proxy SHALL validate the payload and forward the request to the corresponding Admin_API endpoint.

---

### Requirement 9: SSL Certificate Management

**User Story:** As a DevOps user, I want to upload and manage TLS certificates in APISIX, so that I can configure HTTPS termination without accessing the server directly.

#### Acceptance Criteria

1. WHEN a user requests the SSL certificates list, THE APISIX_Dashboard SHALL display all certificates returned by the Admin_API including id, SNI domains, expiry date, and status.
2. WHEN a user uploads a certificate and private key, THE Admin_API_Proxy SHALL accept the PEM-encoded content, construct the Admin_API SSL payload, and forward a PUT request to the Admin_API ssl endpoint.
3. IF the certificate or key content is not valid PEM format, THEN THE Admin_API_Proxy SHALL return an HTTP 422 response with a descriptive error before forwarding to the Admin_API.
4. WHEN a user deletes a certificate, THE Admin_API_Proxy SHALL require explicit user confirmation before sending the DELETE request to the Admin_API.
5. THE APISIX_Dashboard SHALL display a warning indicator for certificates that expire within 30 days.

---

### Requirement 10: Metrics and Monitoring Dashboard

**User Story:** As a DevOps user, I want to view CPU and memory usage of APISIX pods from the Prometheus metrics endpoint, so that I can monitor the health of the APISIX deployment on OpenShift.

#### Acceptance Criteria

1. WHEN a user opens the monitoring tab, THE Metrics_Service SHALL fetch the current Prometheus metrics from the configured metrics endpoint URL.
2. THE Metrics_Service SHALL parse the Prometheus text-format response and extract CPU usage and memory usage metrics per pod.
3. WHEN the metrics endpoint returns a non-2xx response, THE Metrics_Service SHALL return an HTTP 502 response to the dashboard with a descriptive error message.
4. WHEN the metrics endpoint is unreachable, THE Metrics_Service SHALL return an HTTP 503 response to the dashboard within 10 seconds.
5. THE APISIX_Dashboard SHALL display CPU and memory metrics in a visual format (charts or gauges) refreshed at a configurable interval (default 30 seconds).
6. THE Metrics_Service SHALL NOT require credentials to access the Prometheus metrics endpoint unless configured via environment variable.
7. WHERE the metrics endpoint URL is configurable, THE Metrics_Service SHALL read the URL from an environment variable and SHALL NOT hardcode it.

---

### Requirement 11: YAML and JSON Editor Support

**User Story:** As a DevOps user, I want to define APISIX resources using YAML or JSON, so that I can work in the format I am most comfortable with.

#### Acceptance Criteria

1. THE APISIX_Dashboard SHALL provide an editor component that accepts both YAML and JSON input for all resource create and update forms.
2. WHEN a user switches between YAML and JSON modes, THE APISIX_Dashboard SHALL convert the current editor content to the target format without data loss.
3. WHEN a user submits a YAML payload, THE Admin_API_Proxy SHALL convert it to JSON before forwarding to the Admin_API.
4. IF the YAML or JSON content is syntactically invalid, THEN THE APISIX_Dashboard SHALL display an inline syntax error before the user can submit.

---

### Requirement 12: OpenShift Deployment Readiness

**User Story:** As a platform engineer, I want the APISIX Dashboard module to be deployable on OpenShift, so that it can run alongside the existing Fircosoft Dashboard in the production environment.

#### Acceptance Criteria

1. THE Admin_API_Proxy SHALL read all sensitive configuration (Admin API key, Admin API base URL, metrics endpoint URL, JWT secret) exclusively from environment variables.
2. THE APISIX_Dashboard backend SHALL NOT write sensitive configuration values to log files or error responses.
3. THE Admin_API_Proxy SHALL support HTTPS connections to the Admin_API and SHALL validate the server certificate unless the `APISIX_ADMIN_VERIFY_SSL` environment variable is explicitly set to `false`.
4. THE APISIX_Dashboard SHALL function correctly when served behind an OpenShift Route (reverse proxy) without requiring changes to application code.

---

### Requirement 13: LDAP Authentication Integration (Phase 2)

**User Story:** As an enterprise administrator, I want users to authenticate via LDAP, so that APISIX Dashboard access is governed by the organisation's existing identity management system.

#### Acceptance Criteria

1. WHERE LDAP integration is enabled, THE Auth_Service SHALL authenticate users against the configured LDAP server using the ldap3 library.
2. WHERE LDAP integration is enabled, THE Auth_Service SHALL map LDAP group membership to APISIX Dashboard roles (`viewer` or `admin`) based on configurable group-to-role mappings.
3. WHERE LDAP integration is enabled, THE Auth_Service SHALL fall back to local authentication if the LDAP server is unreachable, and SHALL log a warning.
4. WHEN an LDAP-authenticated user's group membership changes, THE Auth_Service SHALL reflect the updated role on the next login.

---

### Requirement 14: Admin Access Approval Flow (Phase 2)

**User Story:** As a local admin, I want to grant admin access to other users only after manager approval, so that elevated privileges are controlled through a documented process.

#### Acceptance Criteria

1. WHEN a local admin promotes a user to the `admin` role, THE Auth_Service SHALL record the promotion request including the requesting admin username, target username, timestamp, and a mandatory manager approval reference.
2. THE Auth_Service SHALL NOT activate the `admin` role for the target user until the promotion record includes a non-empty manager approval reference.
3. WHEN the `admin` role is activated for a user, THE Auth_Service SHALL write an audit log entry including the approving manager reference, the granting admin username, and the target username.
