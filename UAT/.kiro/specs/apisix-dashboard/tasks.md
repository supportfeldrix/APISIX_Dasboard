# Implementation Tasks

## Task List

### Phase 1: Project Scaffolding

- [x] 1.1 Create backend directory structure
  - Create `backend/app/`, `backend/app/models/`, `backend/app/schemas/`, `backend/app/routers/`, `backend/app/services/`, `backend/app/utils/`, `backend/tests/`
  - Create `backend/requirements.txt` with pinned versions: `fastapi==0.111.0`, `uvicorn[standard]==0.29.0`, `sqlalchemy==2.0.30`, `python-jose[cryptography]==3.3.0`, `passlib[bcrypt]==1.7.4`, `httpx==0.27.0`, `pydantic-settings==2.2.1`, `pyyaml==6.0.1`, `ldap3==2.9.1`, `pytest==8.2.0`, `hypothesis==6.100.1`, `pytest-asyncio==0.23.6`, `respx==0.21.1`
  - Create `backend/.env.example` with all required environment variable keys (no values)

- [x] 1.2 Create frontend directory structure
  - Scaffold React + Vite project in `frontend/` using `npm create vite@latest frontend -- --template react`
  - Install dependencies: `react-router-dom@6`, `axios`, `@monaco-editor/react`, `recharts`, `zustand`, `tailwindcss`, `postcss`, `autoprefixer`
  - Configure Tailwind CSS (`tailwind.config.js`, `postcss.config.js`)
  - Configure Vite proxy for `/api` → `http://localhost:8000` in `vite.config.js`

- [x] 1.3 Create docker-compose and nginx configuration
  - Create `docker-compose.yml` with `backend` and `frontend` services
  - Create `nginx/nginx.conf` with static file serving and `/api` proxy pass
  - Create `backend/Dockerfile`

---

### Phase 2: Backend — Configuration and Database

- [x] 2.1 Implement `app/config.py`
  - Define `Settings` class using `pydantic-settings` with all environment variables listed in the design
  - Ensure no default values for `JWT_SECRET`, `APISIX_ADMIN_KEY`, `APISIX_ADMIN_BASE_URL`, `APISIX_METRICS_URL`
  - Export a singleton `settings` instance

- [x] 2.2 Implement `app/database.py`
  - Create SQLAlchemy async engine using `DATABASE_URL` from settings
  - Define `Base` declarative base
  - Define `get_db` dependency for FastAPI dependency injection

- [x] 2.3 Implement `app/models/user.py`
  - Define `User` ORM model with columns: `id`, `username`, `hashed_password`, `role`, `is_active`, `created_at`
  - Add CHECK constraint for `role IN ('viewer', 'admin')`

- [x] 2.4 Implement `app/models/token_blacklist.py`
  - Define `TokenBlacklist` ORM model with columns: `id`, `jti`, `invalidated_at`, `expires_at`
  - Add index on `jti` column

- [x] 2.5 Implement `app/main.py`
  - Create FastAPI app with title, version, and OpenAPI docs
  - Configure CORS middleware using `CORS_ORIGINS` env var
  - Register all routers with `/api` prefix
  - Add startup event handler that calls `seed_admin()` and runs `Base.metadata.create_all()`
  - Set `root_path` from `ROOT_PATH` env var for reverse-proxy compatibility

---

### Phase 3: Backend — Authentication

- [x] 3.1 Implement `app/schemas/auth.py`
  - Define `LoginRequest`, `TokenResponse`, `UserInfo` Pydantic models as specified in the design

- [x] 3.2 Implement `app/services/auth_service.py`
  - Implement `create_access_token(data: dict) -> str` — generates UUID4 JTI, signs JWT with `JWT_SECRET`
  - Implement `verify_token(token: str, db: Session) -> dict` — decodes JWT, checks expiry, checks JTI not in blacklist
  - Implement `authenticate_user(username: str, password: str, db: Session) -> User | None` — bcrypt verify
  - Implement `blacklist_token(jti: str, expires_at: datetime, db: Session)` — inserts into `token_blacklist`
  - Implement `seed_admin(db: Session)` — creates `admin` user with hashed `N03ntry#` if no users exist
  - Implement `get_current_user` FastAPI dependency that calls `verify_token`

- [x] 3.3 Implement `app/routers/auth.py`
  - Implement `POST /api/auth/login` — calls `authenticate_user`, returns `TokenResponse`
  - Implement `POST /api/auth/logout` — extracts JTI from current token, calls `blacklist_token`
  - Implement `GET /api/auth/me` — returns `UserInfo` for current authenticated user
  - Return HTTP 401 with `{"detail": "Invalid username or password"}` on failed login

---

### Phase 4: Backend — Admin API Proxy

- [x] 4.1 Implement `app/utils/yaml_converter.py`
  - Implement `yaml_to_json(yaml_str: str) -> str` — PyYAML safe_load → json.dumps; raise `ValueError` on parse failure
  - Implement `json_to_yaml(json_str: str) -> str` — json.loads → PyYAML dump; raise `ValueError` on parse failure

- [x] 4.2 Implement `app/utils/pem_validator.py`
  - Implement `validate_pem_cert(pem: str) -> bool` — regex check for `-----BEGIN CERTIFICATE-----` / `-----END CERTIFICATE-----`
  - Implement `validate_pem_key(pem: str) -> bool` — regex check for `-----BEGIN.*PRIVATE KEY-----` / `-----END.*PRIVATE KEY-----`

- [x] 4.3 Implement `app/services/proxy_service.py`
  - Define `ALLOWED_RESOURCES: frozenset` = `{"routes", "services", "upstreams", "consumers", "plugins", "ssl", "global_rules", "plugin_metadata"}`
  - Create a shared `httpx.AsyncClient` instance with configurable timeout and SSL verification from settings
  - Implement `forward_request(method, resource_type, sub_path, body, query_params, username) -> httpx.Response`
    - Validate `resource_type` against `ALLOWED_RESOURCES`; raise `HTTPException(400)` if not found
    - Inject `X-API-KEY` header from `settings.APISIX_ADMIN_KEY`
    - Handle `httpx.ConnectError` / `httpx.TimeoutException` → raise `HTTPException(503)`
    - Log every request: `PROXY | {username} | {method} | {resource_type}/{sub_path} | {status_code} | {duration_ms}ms`
  - Implement `convert_body_if_yaml(body: bytes, content_type: str) -> tuple[bytes, str]` — converts YAML body to JSON

- [x] 4.4 Implement `app/schemas/apisix.py`
  - Define `RoutePayload`, `ServicePayload`, `UpstreamPayload`, `ConsumerPayload`, `SSLPayload` Pydantic models with required fields for structural validation
  - Define `ProxyError` response model

- [x] 4.5 Implement `app/routers/proxy.py`
  - Implement catch-all route: `/{resource_type}/{path:path}` for all HTTP methods
  - Apply `get_current_user` dependency for authentication
  - Enforce viewer role: if `user.role == "viewer"` and `request.method != "GET"`, return HTTP 403
  - For SSL PUT requests: validate PEM content using `pem_validator`; return 422 if invalid
  - Call `proxy_service.forward_request` and stream the response back to the caller
  - Mount router at `/api/apisix`

---

### Phase 5: Backend — Metrics Service

- [x] 5.1 Implement `app/services/metrics_service.py`
  - Implement `fetch_metrics() -> str` — async httpx GET to `settings.APISIX_METRICS_URL` with timeout
    - Raise `HTTPException(502)` on non-2xx response
    - Raise `HTTPException(503)` on connection error / timeout
  - Implement `parse_prometheus(text: str) -> list[PodMetrics]`
    - Parse Prometheus text format line by line
    - Extract `container_cpu_usage_seconds_total` and `container_memory_working_set_bytes` metrics
    - Group by `pod` label
    - Return list of `PodMetrics` objects

- [x] 5.2 Implement `app/routers/metrics.py`
  - Implement `GET /api/metrics` — calls `metrics_service.fetch_metrics()` then `parse_prometheus()`
  - Require authentication (`get_current_user` dependency)
  - Return `MetricsResponse` with timestamp and pod metrics list

---

### Phase 6: Backend — Tests

- [x] 6.1 Write unit tests for `auth_service` (`tests/test_auth.py`)
  - Test `create_access_token` produces decodable JWT with correct claims
  - Test `authenticate_user` returns `None` for wrong password
  - Test `seed_admin` creates admin user with bcrypt-hashed password
  - Test `blacklist_token` + `verify_token` rejects blacklisted JTI

- [x] 6.2 Write property-based tests for auth (`tests/test_auth_properties.py`)
  - **Property 1**: `@given(valid_user_strategy)` — valid credentials always return decodable JWT
    - `# Feature: apisix-dashboard, Property 1: Valid credentials always produce a decodable JWT`
  - **Property 2**: `@given(invalid_credentials_strategy)` — invalid credentials always return 401, no token
    - `# Feature: apisix-dashboard, Property 2: Invalid credentials never produce a token`
  - **Property 3**: `@given(st.text(min_size=1))` — passwords stored as bcrypt hashes, never plaintext
    - `# Feature: apisix-dashboard, Property 3: Passwords are always stored as bcrypt hashes`
  - **Property 14**: `@given(valid_token_strategy)` — logout invalidates token for all subsequent requests
    - `# Feature: apisix-dashboard, Property 14: Token logout invalidates the token for all subsequent requests`
  - Configure `@settings(max_examples=100)` on all property tests

- [x] 6.3 Write unit tests for `proxy_service` (`tests/test_proxy.py`)
  - Test path allowlist: allowed paths are forwarded, disallowed paths return 400
  - Test APISIX 503 on connection error (using `respx` mock)
  - Test non-2xx responses are forwarded unchanged
  - Test log entry is produced for every proxied request

- [x] 6.4 Write property-based tests for proxy (`tests/test_proxy_properties.py`)
  - **Property 4**: `@given(viewer_user, non_get_method, allowed_path)` — viewer always gets 403
    - `# Feature: apisix-dashboard, Property 4: Viewer role blocks all non-GET requests`
  - **Property 5**: `@given(admin_user, any_method, allowed_path)` — admin never gets 403
    - `# Feature: apisix-dashboard, Property 5: Admin role permits all CRUD operations`
  - **Property 6**: `@given(protected_endpoint)` — no auth always returns 401
    - `# Feature: apisix-dashboard, Property 6: Unauthenticated requests are always rejected`
  - **Property 7**: `@given(proxy_scenario)` — responses never contain `APISIX_ADMIN_KEY` value
    - `# Feature: apisix-dashboard, Property 7: Proxy responses never contain sensitive credentials`
  - **Property 9**: `@given(st.text())` — arbitrary paths: allowlist enforced correctly
    - `# Feature: apisix-dashboard, Property 9: Path allowlist is enforced for all requests`
  - **Property 10**: `@given(st.integers(400, 599))` — non-2xx forwarded unchanged
    - `# Feature: apisix-dashboard, Property 10: Non-2xx Admin API responses are forwarded unchanged`
  - **Property 11**: `@given(proxy_request_strategy)` — every proxied request produces log entry
    - `# Feature: apisix-dashboard, Property 11: Every proxied request produces a log entry with required fields`
  - Configure `@settings(max_examples=100)` on all property tests

- [x] 6.5 Write property-based tests for YAML converter (`tests/test_yaml_converter.py`)
  - **Property 12a**: `@given(yaml_document_strategy)` — YAML→JSON→YAML round-trip is lossless
    - `# Feature: apisix-dashboard, Property 12: YAML↔JSON conversion is lossless (round-trip)`
  - **Property 12b**: `@given(json_document_strategy)` — JSON→YAML→JSON round-trip is lossless
    - `# Feature: apisix-dashboard, Property 12: YAML↔JSON conversion is lossless (round-trip)`
  - **Property 13**: `@given(invalid_yaml_strategy)` — invalid YAML always raises ValueError
    - `# Feature: apisix-dashboard, Property 13: Syntactically invalid YAML/JSON is always rejected before submission`
  - Configure `@settings(max_examples=100)` on all property tests

- [x] 6.6 Write property-based tests for validation (`tests/test_validation_properties.py`)
  - **Property 8**: `@given(invalid_payload_strategy)` — invalid payloads always return 422 with field errors
    - `# Feature: apisix-dashboard, Property 8: Invalid payloads always return 422 with field-level errors`
  - Configure `@settings(max_examples=100)`

- [x] 6.7 Write property-based tests for metrics and SSL (`tests/test_metrics_properties.py`, `tests/test_ssl_properties.py`)
  - **Property 15**: `@given(st.dates())` — SSL expiry warning shown iff within 30 days
    - `# Feature: apisix-dashboard, Property 15: SSL certificate expiry warning is shown for certs within 30 days`
  - **Property 16**: `@given(prometheus_text_strategy)` — parser extracts correct CPU/memory per pod
    - `# Feature: apisix-dashboard, Property 16: Prometheus metrics parser extracts CPU and memory per pod`
  - Configure `@settings(max_examples=100)` on all property tests

---

### Phase 7: Frontend — Core Setup

- [x] 7.1 Implement `src/api/client.js`
  - Create Axios instance with `baseURL` pointing to FastAPI backend
  - Add request interceptor: attach `Authorization: Bearer <token>` from auth store
  - Add response interceptor: redirect to `/login` on 401; display toast on other errors

- [x] 7.2 Implement `src/store/authStore.js`
  - Zustand store with `{ token, user, role, setAuth, clearAuth }` actions
  - Persist to `sessionStorage` using Zustand persist middleware

- [x] 7.3 Implement `src/hooks/useAuth.js`
  - `useAuth()` hook returning `{ user, role, isAuthenticated, login, logout }`
  - `login(username, password)` — calls `/api/auth/login`, stores token
  - `logout()` — calls `/api/auth/logout`, clears store, redirects to `/login`

- [x] 7.4 Implement `src/App.jsx`
  - React Router v6 `<BrowserRouter>` with routes for all pages
  - `<ProtectedRoute>` wrapper that redirects to `/login` if not authenticated
  - Route definitions: `/login`, `/routes`, `/services`, `/upstreams`, `/consumers`, `/plugins`, `/ssl`, `/monitoring`

- [x] 7.5 Implement `src/components/Layout.jsx`
  - Sidebar with navigation links to all resource pages
  - Topbar with current username, role badge, and logout button
  - Responsive layout using Tailwind CSS

---

### Phase 8: Frontend — Shared Components

- [x] 8.1 Implement `src/components/ResourceTable.jsx`
  - Generic table component accepting `columns` and `data` props
  - Client-side pagination (configurable page size)
  - Action buttons: Edit, Enable/Disable (for routes), Delete
  - Loading skeleton state

- [x] 8.2 Implement `src/components/ResourceEditor.jsx`
  - Wraps `@monaco-editor/react` with YAML and JSON language support
  - Toggle button to switch between YAML and JSON modes
  - On mode switch: call `yaml_to_json` or `json_to_yaml` conversion (via backend `/api/util/convert` endpoint or client-side using `js-yaml`)
  - Disable submit button while Monaco reports syntax errors
  - Expose `getValue()` and `isValid()` methods via `useImperativeHandle`

- [x] 8.3 Implement `src/components/ConfirmDialog.jsx`
  - Modal dialog with configurable title, message, and confirm/cancel buttons
  - Used for all delete operations
  - Accessible: focus trap, ESC to cancel, ARIA role="dialog"

- [x] 8.4 Implement `src/components/CertWarning.jsx`
  - Badge component that accepts an `expiryDate` prop
  - Displays amber warning badge if expiry is within 30 days
  - Displays red critical badge if expiry is within 7 days
  - No badge if expiry is more than 30 days away

---

### Phase 9: Frontend — Resource Pages

- [x] 9.1 Implement `src/pages/Login.jsx`
  - Username and password form
  - Calls `useAuth().login()` on submit
  - Displays error message on 401
  - Redirects to `/routes` on success

- [x] 9.2 Implement `src/pages/Routes.jsx`
  - Fetch and display routes list using `ResourceTable`
  - Columns: id, name, uri, methods, status, upstream_id
  - Enable/Disable toggle buttons (admin only)
  - Create/Edit button opens `ResourceEditor` in a slide-over panel
  - Delete button opens `ConfirmDialog` (admin only)

- [x] 9.3 Implement `src/pages/Services.jsx`
  - Fetch and display services list using `ResourceTable`
  - Columns: id, name, upstream_id, plugin count
  - Create/Edit/Delete with same pattern as Routes page

- [x] 9.4 Implement `src/pages/Upstreams.jsx`
  - Fetch and display upstreams list using `ResourceTable`
  - Columns: id, name, type (load-balancing algorithm), node count
  - Create/Edit/Delete with same pattern as Routes page

- [x] 9.5 Implement `src/pages/Consumers.jsx`
  - Fetch and display consumers list using `ResourceTable`
  - Columns: username, plugins (count), created_at
  - Create/Edit/Delete with same pattern as Routes page

- [x] 9.6 Implement `src/pages/Plugins.jsx`
  - Two sections: Global Rules and Plugin Metadata
  - Display global rules list and plugin metadata list
  - Edit buttons open `ResourceEditor` for each entry (admin only)

- [x] 9.7 Implement `src/pages/SSL.jsx`
  - Fetch and display SSL certificates list using `ResourceTable`
  - Columns: id, SNI domains, expiry date (with `CertWarning` badge), status
  - Upload form: two textarea inputs for certificate PEM and private key PEM
  - Delete with `ConfirmDialog` (admin only)

- [x] 9.8 Implement `src/pages/Monitoring.jsx`
  - Implement `src/hooks/useMetrics.js` — polls `/api/metrics` at configurable interval (default 30 s)
  - Implement `src/components/MetricsChart.jsx` — Recharts `AreaChart` for CPU and memory per pod
  - Display last-updated timestamp
  - Display error state if metrics fetch fails

---

### Phase 10: Integration and Deployment

- [x] 10.1 Add `pytest.ini` and `conftest.py` to backend
  - Configure pytest markers: `integration`, `property`
  - Configure Hypothesis profiles: `ci` (100 examples), `dev` (20 examples)
  - Add `conftest.py` with test database fixture (in-memory SQLite) and mock APISIX client fixture using `respx`

- [x] 10.2 Verify end-to-end local development setup
  - Start backend with `uvicorn app.main:app --reload` from `backend/`
  - Start frontend with `npm run dev` from `frontend/`
  - Verify login flow, proxy calls, and metrics display work end-to-end

- [x] 10.3 Run full test suite and fix any failures
  - Run `pytest` from `backend/` — all unit and property tests must pass
  - Run `npm test -- --run` from `frontend/` — all component tests must pass

- [x] 10.4 Verify OpenShift deployment readiness
  - Build backend Docker image: `docker build -t apisix-dashboard-backend ./backend`
  - Build frontend: `npm run build` from `frontend/`
  - Verify nginx serves frontend and proxies `/api` correctly
  - Verify all sensitive config is read from environment variables (no hardcoded values)
  - Verify `APISIX_ADMIN_VERIFY_SSL=false` disables TLS verification for Admin API calls
