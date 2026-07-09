# APISIX Dashboard — Project Knowledge Base

## Project Overview

CRO IT custom APISIX management dashboard deployed on OpenShift. Provides real-time route management, SSL certificate monitoring, pod metrics/health dashboards, and role-based access control for the FNB APISIX API gateway infrastructure.

This workspace contains two environments:
- **PROD/** — Production deployment
- **UAT/** — Testing/staging environment

## Architecture

### Stack
- **Backend**: Python 3.14, FastAPI, SQLAlchemy (SQLite on PVC), uvicorn
- **Frontend**: React (Vite), Zustand state management, Tailwind CSS, Axios
- **Auth**: LDAP (Active Directory) + local bcrypt accounts, JWT tokens (jose)
- **Deployment**: OpenShift (OCP), binary builds via `oc start-build --from-dir`
- **Proxy**: Nginx reverse proxy in frontend container → backend service DNS

### Key Services
| Service | Purpose |
|---------|---------|
| `ldap_service.py` | LDAP/AD authentication with 2FA/MFA support |
| `auth_service.py` | JWT creation, bcrypt hashing, user auto-provisioning |
| `metrics_service.py` | Prometheus metrics from APISIX |
| `k8s_service.py` | OpenShift pod health via K8s API |
| `notification_service.py` | Alert rule evaluation + SMTP dispatch |
| `background_scheduler.py` | Periodic notification eval + version check |
| `health_check_prober.py` | Active health probing for upstream services |
| `traffic_report_service.py` | Traffic analysis and reporting |

### Frontend Architecture
- State: Zustand with `sessionStorage` persistence (`authStore.js`)
- API client: Axios with auto-attach Bearer token interceptor
- Session timeout: 30-minute inactivity auto-logout
- 401 interceptor: clears auth and redirects to `/login`

## Environment Configuration

| Setting | UAT | PROD |
|---------|-----|------|
| Cluster | `https://api.dev-02-rb.ocp.fnb.co.za:6443` | `https://api.prod-01-rb.ocp.fnb.co.za:6443` |
| Namespace | `cro-apisix-uat` | `cro-apisix-prod` |
| Route | `https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb.ocp.fnb.co.za` | `https://cro-apisix-croit-dashboard-prod.apps.prod-01-rb.ocp.fnb.co.za` |
| APISIX Admin URL | `http://apisix-dashboard.cro-apisix-uat.svc.cluster.local:9180` | `http://apisix-admin-api.cro-apisix-prod.svc.cluster.local:9180` |
| CORS Origin | `https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb...` | `https://cro-apisix-croit-dashboard-prod.apps.prod-01-rb...` |
| APP_ENVIRONMENT | `UAT` | `PROD` |
| OC CLI | `UAT\oc\oc.exe` | `PROD\oc\oc.exe` |

**UAT Note**: Previously used a direct pod IP for APISIX Admin (caused issues on pod restart). Fixed June 2026 — now uses stable Service DNS (`apisix-dashboard.cro-apisix-uat.svc.cluster.local:9180`) via the `apisix-dashboard` ClusterIP Service (selector: `app: apisix`, port 9180). The `allow_admin` config in APISIX already permits `192.168.0.0/16` which covers all pod-to-pod traffic through the Service.

## OpenShift Deployment

### Before Deploying — Run Tests
```bash
cd <ENV>/backend
python -m pytest tests/test_auth.py tests/test_proxy.py tests/test_yaml_converter.py -v --tb=short
```
Only deploy if tests pass. Ignore Hypothesis `DeadlineExceeded` timing flakes.

### Backend Deployment (Most Common)
```bash
# 1. Login
oc login --token=<token> --server=<CLUSTER_URL>
oc project <NAMESPACE>

# 2. Build & push (from <ENV>/backend/ directory)
oc start-build apisix-dashboard-backend --from-dir=. --follow -n <NAMESPACE>

# 3. Restart to pick up new image
oc rollout restart deployment/apisix-dashboard-backend -n <NAMESPACE>

# 4. Verify
oc rollout status deployment/apisix-dashboard-backend -n <NAMESPACE>
oc get pods -l component=backend -n <NAMESPACE>
```

### Frontend Deployment
```bash
# 1. Build frontend locally first
cd <ENV>/frontend
npx vite build

# 2. Push (needs dist/ present)
oc start-build apisix-dashboard-frontend --from-dir=. --follow -n <NAMESPACE>
oc rollout restart deployment/apisix-dashboard-frontend -n <NAMESPACE>
```

### Build Strategy
Both Dockerfiles use an **incremental overlay pattern**: `FROM` the existing registry image and COPY updated code on top. Avoids Docker Hub rate limits. Builds take ~60s.

### Image Registry
- UAT: `image-registry.openshift-image-registry.svc:5000/cro-apisix-uat/`
- PROD: `image-registry.openshift-image-registry.svc:5000/cro-apisix-prod/`
- Images: `apisix-dashboard-backend:1.0.0`, `apisix-dashboard-frontend:1.0.0`

### Pod Health Checks
- **Liveness**: `GET /health` (backend:8000), `GET /healthz` (frontend:8080)
- **Note**: Backend startup takes 10-15s. 1-2 restart cycles on deploy is normal.

## LDAP Authentication — Lessons Learned

### How It Works
1. User enters AD credentials on login page
2. Backend tries local DB auth first (fast path)
3. If not local user → LDAP bind against `ldaps://ldap.fnbconnect.co.za:636`
4. FNB AD triggers **2FA/MFA push notification** on user's phone during LDAP bind
5. User approves MFA → bind succeeds → JWT issued
6. LDAP users are auto-created in local DB on first login (viewer role by default)

### Critical Timeout Configuration
The LDAP bind triggers a corporate MFA challenge that takes 15-30 seconds. All timeouts must accommodate this:

| Setting | Value | Why |
|---------|-------|-----|
| `LDAP_HARD_TIMEOUT` | 60s | ThreadPoolExecutor wrapping the entire LDAP operation |
| `receive_timeout` | 55s | ldap3 Connection socket timeout (must be < hard timeout) |
| `connect_timeout` | 5s | Initial TCP connection (no MFA involved) |
| `proxy_read_timeout` (nginx) | 60s | Nginx waiting for backend response |

### Service Account Fallback
Two auth paths exist:
1. **Service account bind** → search for user DN → bind as user (when `LDAP_BIND_PASSWORD` is correct)
2. **Direct user bind** → `username@fnb.co.za` (fallback when service account fails)

If the service account password is wrong/expired, the code gracefully falls back to direct bind.

### Bug Fix (June 2026)
**Problem**: Frontend "resets" after 2FA prompt — user can't log in.
**Root cause**: `LDAP_HARD_TIMEOUT` was 8s — too short for MFA push round-trip. Timeout → None → 401 → axios interceptor cleared auth → redirect.
**Fix**: Increased timeouts to 60/55s + added service account fallback to direct bind.

## Configuration

### Secrets (K8s Secret `apisix-dashboard-secrets`)
- `JWT_SECRET` — signing key for JWT tokens
- `APISIX_ADMIN_KEY` — APISIX Admin API key
- `LDAP_BIND_PASSWORD` — LDAP service account password

### ConfigMap (`apisix-dashboard-config`)
All non-sensitive settings: LDAP server, metrics URLs, SMTP config, CORS, etc.

### Internal Service DNS
| Service | UAT | PROD |
|---------|-----|------|
| Backend | `apisix-dashboard-backend.cro-apisix-uat.svc.cluster.local:8000` | `apisix-dashboard-backend.cro-apisix-prod.svc.cluster.local:8000` |
| APISIX Admin | `apisix-dashboard.cro-apisix-uat.svc.cluster.local:9180` | `apisix-admin-api.cro-apisix-prod.svc.cluster.local:9180` |
| Metrics | `apisix-metrics.cro-apisix-uat.svc.cluster.local:9091` | `apisix-metrics.cro-apisix-prod.svc.cluster.local:9091` |

### Local Development
```bash
# Backend (http://localhost:8000)
cd UAT/backend
python run.py

# Frontend (http://localhost:5173)
cd UAT/frontend
npm run dev
```

## Testing

```bash
cd <ENV>/backend
python -m pytest tests/ -v --tb=short
```

- Tests use in-memory SQLite
- `conftest.py` sets env vars before importing app modules
- `APP_ENVIRONMENT` must be defined in `Settings` class
- Hypothesis property tests have tight deadlines — `DeadlineExceeded` errors are noise

### Utility Scripts (UAT)
- `enable_prometheus_plugin.py` — enables prometheus plugin on APISIX routes
- `check_routes.py` — validates APISIX route configuration

## User Management — Delete User Feature (June 2026)

### What It Does
Admins can permanently delete user accounts from the Settings tab. A red "Delete" button appears on each user row (except your own). Clicking it shows a confirmation dialog before executing.

### Backend — `app/routers/users.py`

**Endpoint:** `DELETE /users/{username}`

**Guard logic (evaluated in order):**
1. Admin role check → 403
2. Username format validation (regex `^[a-zA-Z0-9._-]{1,128}$`) → 400
3. Self-delete prevention → 400
4. User existence check → 404
5. Last admin protection (can't delete the only admin) → 400

**Audit logging:**
- Success: audit entry with action="DELETE", status="success" committed atomically with the delete
- Failure: audit entry with status="failed" and rejection reason committed before HTTPException
- Uses inline `AuditLog` creation (not `audit_service.log_action`) to maintain single-transaction atomicity
- Helper function `_audit_failed()` handles all rejection audit entries

**Session invalidation:** Implicit — `get_current_user` already returns 401 when user row is missing. No token blacklist needed.

### Frontend — `src/pages/Settings.jsx`

**State added:**
- `deleteTarget` — username string or null (controls which user is being deleted)
- `deleting` — boolean (loading state for the delete request)

**Handler:** `handleDeleteUser(username)`
- Calls `apiClient.delete(/users/${username}, { timeout: 30000 })`
- Success: green notification auto-dismisses after 5 seconds, refreshes user list
- Error: red notification with API error detail, persists until manually dismissed (X button)
- Timeout: shows "Request timed out. Please try again."

**UI:**
- Red "Delete" button in actions column (hidden for current user's row)
- `ConfirmDialog` with title "Delete User", danger variant, message includes username
- Confirm button disabled with spinner while request is in flight

### Frontend — `src/components/ConfirmDialog.jsx`

**Enhancement:** Added `disabled` prop (boolean, default false):
- When true: confirm button shows inline SVG spinner, has `opacity-50 cursor-not-allowed`, `onClick` suppressed
- Accessibility: sets `disabled` and `aria-disabled` attributes

### Files Modified (both UAT and PROD)
| File | Change |
|------|--------|
| `backend/app/routers/users.py` | Added DELETE endpoint + `_audit_failed()` helper + imports for `re`, `datetime`, `Path`, `Request`, `AuditLog` |
| `frontend/src/components/ConfirmDialog.jsx` | Added `disabled` prop with spinner |
| `frontend/src/pages/Settings.jsx` | Added delete state, handler, button, dialog, dismiss-able error notifications |

### How to Revert
If the delete feature needs to be rolled back:
1. Replace `users.py` with the version before — remove the `@router.delete` function and `_audit_failed()` helper, revert imports to remove `re`, `datetime`, `Path`, `Request`, `AuditLog`
2. Remove `disabled` prop from ConfirmDialog (revert to original confirm button without disabled/spinner logic)
3. In Settings.jsx: remove `deleteTarget`/`deleting` state, `handleDeleteUser` function, the Delete button in the table, and the ConfirmDialog at the bottom
4. Redeploy backend and frontend

## UAT APISIX Admin — Pod IP to Service DNS Migration (June 2026)

### What Was Fixed
UAT dashboard backend was configured with a direct APISIX pod IP (`192.168.84.90:9180`). Every time APISIX pods restarted, the IP changed and required manual ConfigMap updates + backend restart.

### Root Cause of Original 403
The `allow_admin` in APISIX `config.yaml` already permits `192.168.0.0/16` — which covers all pod-to-pod traffic. The original 403 issue was likely a misconfiguration that was since fixed. The Service DNS works correctly now.

### Fix Applied
| Setting | Before | After |
|---------|--------|-------|
| `APISIX_ADMIN_BASE_URL` (ConfigMap) | `http://192.168.84.90:9180` | `http://apisix-dashboard.cro-apisix-uat.svc.cluster.local:9180` |

### How It Works
- Service `apisix-dashboard` (ClusterIP) in `cro-apisix-uat` namespace
- Selector: `app: apisix` → routes to APISIX StatefulSet pods
- Port: 9180 → targetPort: 9180
- Kubernetes DNS resolves to current pod endpoints regardless of IP changes

### APISIX allow_admin Config (for reference)
```yaml
allow_admin:
  - 10.0.0.0/8
  - 172.16.0.0/12
  - 192.168.0.0/16    # Covers all pod-to-pod traffic
  - 127.0.0.0/8
```

## Resetting Route Traffic Counters (Pre-Go-Live)

### Why You'd Want This
The Route Traffic dashboard reads live Prometheus counters (`apisix_http_status`) from APISIX. These are cumulative counters stored in nginx shared memory. They are NOT stored in the dashboard database — there's nothing to clear on the dashboard side.

### How to Reset
The only way to zero the counters is to **restart the APISIX pods** (clears nginx shared memory):

```bash
oc login --token=<token> --server=https://api.dev-02-rb.ocp.fnb.co.za:6443
oc project cro-apisix-uat
oc rollout restart statefulset/apisix-uat -n cro-apisix-uat
oc rollout status statefulset/apisix-uat -n cro-apisix-uat --timeout=120s
```

Since UAT now uses Service DNS, no ConfigMap update is needed after the restart.

### What Does NOT Work
- Plugin reload (`PUT /apisix/admin/plugins/reload`) — reloads plugin code but does NOT reset Prometheus counters
- Hard-refreshing the browser — counters are server-side, not cached in the frontend
- Clearing browser cache/cookies — same reason

## Alert Rules — Metrics Lookup Key Mismatch Fix (June 2026)

### What Was Fixed
Alert rules for metric-based conditions (UPSTREAM_ERROR, JWT_FAILURE, HIGH_ERROR_RATE) were never firing on PROD. Routes received 500 errors but no email notifications were sent.

### Root Cause
The Prometheus plugin on APISIX PROD reports the `route` label using the **route name** (e.g., `route="RCM - OAuth2"`) rather than the numeric route ID (e.g., `593676047602418605`). The `parse_route_status_metrics()` function in `metrics_evaluator.py` extracts whatever is in the `route="..."` label as the dict key.

Meanwhile, alert rules store the numeric `route_id` from the APISIX Admin API. When `_evaluate_metric_rule()` looked up `route_metrics.get("593676047602418605")`, it got `None` because the actual key was `"RCM - OAuth2"`. Result: every metric-based rule was silently skipped.

### Fix Applied (both UAT and PROD)
In `backend/app/services/background_scheduler.py`, method `_evaluate_metric_rule()`:

```python
# Before:
route_id = rule.route_id

# After:
route_id = rule.route_id
if route_id not in route_metrics and rule.route_name:
    route_id = rule.route_name
```

This tries the numeric route_id first (in case some APISIX configs use it), then falls back to route_name.

### Key Insight
The `route` label in `apisix_http_status` Prometheus metrics depends on APISIX configuration:
- If the route has a `name` field set → Prometheus uses the name (e.g., `"RCM - OAuth2"`)
- If the route has no name → Prometheus uses the numeric route ID

Since all PROD routes have friendly names configured, the metrics always use the name. The alert rules store both `route_id` (numeric) and `route_name` (friendly), so the fallback covers both cases.

### How to Verify
After deploying, wait for the next evaluation cycle (configured by `NOTIFICATION_EVAL_INTERVAL`). If a route currently has 5xx errors in Prometheus, an alert email should fire within one cycle. Check notification_logs table for new entries with the route's alert_rule_id.

## Alert Rules — High-Water Mark Evaluation for UPSTREAM_ERROR and CLIENT_ERROR (July 2026)

### What Was Fixed
UPSTREAM_ERROR and CLIENT_ERROR alert rules were firing false alerts after every dashboard pod restart, and intermittently during normal operation due to load-balancer jitter between APISIX pods.

### Root Cause — Load-Balancer Jitter
The `apisix-metrics` ClusterIP Service load-balances scrape requests between APISIX pods (`apisix-0` and `apisix-1`). Each pod has its own **independent** Prometheus counters. When the metrics scrape alternates between pods, the aggregated sum bounces:
- Cycle 1: scrape hits apisix-0 → total 5xx = 137
- Cycle 2: scrape hits apisix-1 → total 5xx = 140
- Old delta logic: `140 - 137 = 3` → alert fires (false positive)

Additionally, on pod restart `_previous_metrics` was empty, causing the entire cumulative counter to appear as "new" errors.

### Fix Applied (both UAT and PROD)
Both UPSTREAM_ERROR and CLIENT_ERROR now use a **high-water mark** pattern instead of simple deltas:

1. Tracks the **maximum** error count ever seen per route (the HWM never decreases)
2. `delta = current_count - high_water_mark`
3. Alert triggers only when `delta >= threshold` (current exceeds all-time max)
4. Load-balancer bouncing below the HWM is silently ignored
5. First cycle after pod restart: `_baseline_established` flag skips all metric evaluation — stores baseline only

The HWM is stored per-route using dedicated keys:
- UPSTREAM_ERROR: `self._previous_metrics[f"__upstream_error__{route_id}"]["__hwm_5xx__"]`
- CLIENT_ERROR: `self._previous_metrics[f"__client_error__{route_id}"]["__hwm_4xx__"]`

### Behavior After Fix
| Event | Result |
|-------|--------|
| Pod restart | First cycle stores baseline, no alert |
| Load-balancer jitter (count bounces below HWM) | No alert |
| Genuine new 500 error (count exceeds HWM) | Alert fires, HWM updated |
| Traffic recovers (new 2xx, no new 5xx above HWM) | Recovery email sent |
| Normal 200 traffic continues | No emails |

### Recovery Logic
Recovery emails are sent when:
- `delta_5xx <= 0` (no new errors above HWM) AND `delta_2xx > 0` (healthy traffic flowing)
- `check_recovery()` prevents duplicate recovery emails (only sends once per alert cycle)

### Important Notes
- JWT_FAILURE and HIGH_ERROR_RATE still use the original cumulative logic (not HWM-based)
- The `_baseline_established` flag is set after the first complete evaluation cycle
- The HWM resets only when the dashboard pod restarts (memory-only, not persisted to DB)
- On APISIX pod restart, Prometheus counters reset to 0 — the HWM will naturally be exceeded again on the first real error after that

## LDAP Timeout Alignment (June 2026)

### What Was Fixed
UAT LDAP service had misaligned timeouts compared to PROD, and was missing the service account fallback.


### Changes Applied to UAT `ldap_service.py`
| Setting | Before (UAT) | After (aligned to PROD) |
|---------|-------------|------------------------|
| `connect_timeout` | 10s | 5s |
| Service account `receive_timeout` | 10s | 55s |
| User bind `receive_timeout` | 45s | 55s |
| Service account fallback | Missing | Added — falls back to direct bind if service account fails |
| `_direct_bind_authenticate()` | Inline code block | Extracted to separate function (matches PROD pattern) |

### Why These Values
- `connect_timeout=5` — TCP connection to LDAP server, no MFA involved, should be fast
- `receive_timeout=55` — Must accommodate 2FA/MFA push notification round-trip (15-30s typical, up to 55s)
- `LDAP_HARD_TIMEOUT=60` — Outer ThreadPoolExecutor timeout, must be > receive_timeout
- `proxy_read_timeout=60s` (nginx) — Must be >= LDAP_HARD_TIMEOUT so nginx doesn't kill the connection

### How to Verify LDAP Is Working
1. Login with an AD user (triggers MFA push)
2. User should see MFA prompt on their phone within 5 seconds
3. After approving, login should complete within 30 seconds total
4. If login resets/fails: check `LDAP_HARD_TIMEOUT` is 60s and all `receive_timeout` values are 55s

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Frontend resets on LDAP login | LDAP timeout too short for MFA | Ensure `LDAP_HARD_TIMEOUT` is 60s, all `receive_timeout` = 55s |
| Pod crash-loops on deploy | Liveness probe fires before startup | Normal — recovers after 1-2 restarts |
| APISIX Admin returns 403 | `allow_admin` restricts source IPs | Both UAT and PROD now use Service DNS (resolved June 2026) |
| APISIX 403 after pod restart | Pod IP changed (UAT only) | No longer an issue — UAT switched to Service DNS (June 2026) |
| `pydantic ValidationError: extra_forbidden` | `.env` has field not in Settings | Add field to `Settings` class with default |
| CORS errors in browser | Route URL doesn't match `CORS_ORIGINS` | Update ConfigMap and restart |
| Service account bind fails | Wrong/placeholder password | Code falls back to direct bind automatically |
| Can't delete users | Feature not deployed | Ensure `users.py` has the DELETE endpoint (added June 2026) |
| Delete button missing for a user | It's your own account | By design — cannot delete yourself |
| "Cannot delete the last admin user" | Only one admin left | Promote another user to admin first |
| Metric alert rules never fire | Prometheus `route` label uses route name, not numeric ID | Fixed June 2026 — `_evaluate_metric_rule()` falls back to `route_name` if `route_id` not found in metrics |
| 4xx errors not triggering alerts | Only UPSTREAM_ERROR (5xx) was monitored | Use new CLIENT_ERROR condition type (added June 2026) — alerts on 400–499 codes |
| Uptime chart not showing on Log Viewer | Logs are in raw nginx format (not JSON) | Chart only renders for route-specific JSON logs, not access.log/error.log |
| RouteUptimePanel shows wrong data for Yesterday/hour presets | `tail -20000` too shallow + cross-midnight presets only showed today | Fixed July 2026 — dynamic tail depth + multi-day fetch & merge |
| False alert emails after pod restart | Load-balancer jitter between APISIX pods + empty `_previous_metrics` on restart | Fixed July 2026 — high-water mark evaluation + `_baseline_established` flag skips first cycle |
| Build fails with `CannotCreateBuildPod` | ResourceQuota `example` added to namespace requires resource limits on build pods | Patch BuildConfig: add `spec.resources` with `limits.cpu=1, limits.memory=1Gi, requests.cpu=250m, requests.memory=256Mi` |
| 413 on chunked POST requests (RTS/RCM) | APISIX 3.17 `apisix_delay_client_max_body_check on` misinterprets `client_max_body_size 0` as "zero allowed" for chunked bodies | Add `client-control` plugin with `max_body_size: 10485760` to each affected route (fixed UAT July 2026, pending PROD) |
| Backend OOMKilled when viewing RCM logs | WebSocket exec transfers too much data (RCM log entries are 3-8KB each); 5000 lines = 25-40MB exceeds 512Mi pod limit | Fixed July 2026 — `head -500` limit + memory bump to 768Mi + WebSocket `max_bytes` cap (see section below) |
| Traffic report shows "No data" for Today | WebSocket "no close frame" timeout when transferring large volumes over K8s exec API | Fixed July 2026 — reduced matching line limit from 5000 to 500 per pod; ~2.5MB transfers reliably within 30s timeout |

## Traffic Report WebSocket OOM & Timeout Fix (July 2026)

### What Was Fixed
1. Backend pod was OOMKilled (exit 137) when users opened the RCM Log Viewer
2. Traffic report chart showed "No traffic data found" for Today (but Yesterday worked)

### Root Cause — OOM (512Mi limit exceeded)
The `_exec_in_pod_ws()` function in `traffic_report_service.py` accumulated ALL stdout data from the K8s WebSocket exec API without any size limit. When the log viewer and traffic report fired concurrently (both reading from large log files), memory usage exceeded the 512Mi pod limit.

### Root Cause — "No data" for Today
RCM log entries are **3-8KB each** because they contain full multipart request bodies with JWT tokens. The original `head -5000` limit meant the WebSocket had to transfer 5000 × 5KB = **~25MB** of data per pod. The K8s exec WebSocket connection dropped mid-transfer with "no close frame received or sent" error. Yesterday worked because `tac` processes differently and historical data was smaller.

### Fixes Applied (UAT `traffic_report_service.py`)

| Change | Before | After | Why |
|--------|--------|-------|-----|
| `_exec_in_pod_ws` max_bytes | No limit | 10MB cap | Prevents OOM — breaks out of read loop when exceeded |
| `_exec_in_pod_ws` max_size | Default | 10MB per frame | Prevents single large WebSocket frame from blowing memory |
| WebSocket `open_timeout` | 10s | 15s | More time to establish connection |
| WebSocket `close_timeout` | 5s | 30s | Allows time for large data to flush before close |
| WebSocket `ping_timeout` | None | 30s | Keeps connection alive during large transfers |
| Route log lines (today) | `head -5000` | `tail -500` | Keeps transfer under ~2.5MB per pod (500 × 5KB) |
| Route log lines (historical) | `head -10000` | `head -500` | Same — limits data volume |
| Pod memory limit | 512Mi | 768Mi | Extra headroom for Python + concurrent WebSocket reads |
| Pod memory request | 128Mi | 256Mi | Matches actual baseline usage |
| Log viewer max lines | 1000 | 500 | Reduces concurrent memory pressure |
| Log viewer tail depth | `lines * 3` | `min(lines * 5, 5000)` | Caps search depth with explicit limit |

### Key Insight — Log Entry Sizes Vary Wildly by Route
| Route | Avg Line Size | 500 lines = |
|-------|---------------|-------------|
| RTS (realtime-screening.log) | ~1KB | ~500KB ✅ |
| RCM (rcm-route.log) | 3-8KB | ~2.5MB ✅ |
| Keycloak (keycloak-access.log) | ~500B | ~250KB ✅ |
| access.log (raw nginx) | ~200B | ~100KB ✅ |

The `tail -500` limit is conservative enough for RCM (heaviest route) while still providing enough data for meaningful charts. Yesterday's RCM traffic had 103 requests total — 500 lines per pod (1000 total across 2 pods) covers even busy days.

### How the Traffic Report Works (Post-Fix)
```
Frontend: GET /api/metrics/traffic-report?route_id=rcm-injecting-jwt&date=2026-07-09&time_from=00:00&time_to=23:59
    │
    ▼
Backend: for each pod in [apisix-uat-0, apisix-uat-1]:
    │   WebSocket exec → sh -c "tail -20000 <log_file> | grep -a '<route_id>' | tail -500"
    │   (today: tail grabs last 20k lines, grep filters by route, tail -500 limits output)
    │   
    │   OR for historical (days_ago > 0):
    │   WebSocket exec → sh -c "tac <log_file> | grep -a '<route_id>' | head -500"
    │   (tac reads file backwards, grep filters, head limits to 500 matches)
    │
    ▼
Backend: Parse JSON lines → extract start_time, latency, response.status
    │   Filter by target_date and time range
    │   Group by minute → per_minute counts/latency/statuses
    │
    ▼
Frontend: Render response time chart + outage timeline + error events table
```

### Files Modified (UAT only — pending PROD promotion)
| File | Change |
|------|--------|
| `backend/app/services/traffic_report_service.py` | Added max_bytes/max_size/timeout caps to WebSocket, reduced line limits to 500 |
| `backend/app/routers/logs.py` | Reduced max lines to 500, capped tail depth at 5000, added search input sanitisation |

### How to Verify
1. Open the dashboard → Logs page
2. Select "RCM - OAuth2" log file
3. Click "Fetch Logs" — raw log lines should appear
4. Select "Today" in the chart timeframe → chart should render with data points
5. Check pod events: `oc describe pod <backend-pod>` — should show 0 OOMKill events
6. Memory usage: `oc adm top pod <backend-pod>` — should stay well under 768Mi

### If Traffic Report Returns Empty
1. Check pod logs for "WebSocket exec failed" errors
2. If "no close frame" persists, further reduce `tail -500` to `tail -200`
3. If "Timeout exec'ing into pod" appears, the APISIX pod may be unresponsive
4. Verify APISIX pods are running: `oc get pods -l app=apisix -n cro-apisix-uat`

## Promoting UAT → PROD

1. Make and test changes in UAT
2. Apply same code changes to PROD folder (both maintain separate copies)
3. Run tests in PROD/backend
4. Login to PROD cluster and deploy
5. **Important:** When copying files between environments, search for "PROD" or "UAT" references to avoid cross-contamination

### Pending PROD Changes (June/July 2026)

| File | Change | Status |
|------|--------|--------|
| `backend/app/routers/metrics.py` | Traffic report CSV export uses friendly route name (`ROUTE_NAMES`) instead of raw `route_id`. Also uses friendly name in filename. | Applied to UAT, **not yet applied to PROD** |
| `backend/app/services/traffic_report_service.py` | WebSocket OOM fix: max_bytes cap, timeout increases, line limit reduced to 500 | Applied to UAT, **not yet applied to PROD** |
| `backend/app/routers/logs.py` | Log viewer: max lines reduced to 500, tail depth capped at 5000, search input sanitisation | Applied to UAT, **not yet applied to PROD** |
| Deployment memory limits | Pod memory: requests 256Mi, limits 768Mi (was 128Mi/512Mi) | Applied to UAT, **not yet applied to PROD** |
| APISIX Route: RTS (secured) | Add `client-control` plugin with `max_body_size: 10485760` to fix 413 on chunked requests | Applied to UAT, **not yet applied to PROD** |
| APISIX Route: RCM (secured) | Add `client-control` plugin with `max_body_size: 10485760` to fix 413 on chunked requests | Applied to UAT, **not yet applied to PROD** |

#### How to Apply the Chunked Body Fix to PROD (413 Fix)

**Background:** APISIX 3.17 with `apisix_delay_client_max_body_check on` (auto-generated) misinterprets `client_max_body_size 0` as "zero bytes allowed" for chunked `Transfer-Encoding` requests. This causes `413 Request Entity Too Large` even though the global config says unlimited. The fix is adding the `client-control` plugin with an explicit `max_body_size` to each affected route.

**Steps:**

1. Login to PROD cluster:
   ```bash
   oc login --token=<token> --server=https://api.prod-01-rb.ocp.fnb.co.za:6443
   oc project cro-apisix-prod
   ```

2. Apply to the RTS route (find the PROD route ID first):
   ```bash
   # List routes to find the correct IDs
   oc exec <apisix-pod> -c apisix -n cro-apisix-prod -- \
     curl -s http://localhost:9180/apisix/admin/routes \
     -H "X-API-KEY: <PROD_ADMIN_KEY>" | python -m json.tool | grep -A2 '"id"'

   # Patch RTS route
   oc exec <apisix-pod> -c apisix -n cro-apisix-prod -- \
     curl -s -X PATCH http://localhost:9180/apisix/admin/routes/<RTS_ROUTE_ID> \
     -H "X-API-KEY: <PROD_ADMIN_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"plugins": {"client-control": {"max_body_size": 10485760}}}'
   ```

3. Patch RCM route:
   ```bash
   oc exec <apisix-pod> -c apisix -n cro-apisix-prod -- \
     curl -s -X PATCH http://localhost:9180/apisix/admin/routes/<RCM_ROUTE_ID> \
     -H "X-API-KEY: <PROD_ADMIN_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"plugins": {"client-control": {"max_body_size": 10485760}}}'
   ```

4. Verify (send a chunked test request from inside the pod):
   ```bash
   oc exec <apisix-pod> -c apisix -n cro-apisix-prod -- \
     sh -c "dd if=/dev/urandom bs=3200 count=1 2>/dev/null | \
     curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:9080/rest/api/services/RealTimeWSProvider \
     -H 'Host: <PROD_HOST>' -H 'Transfer-Encoding: chunked' -H 'Content-Type: application/json' --data-binary @-"
   ```
   Expected: any status OTHER than 413 (likely 500 or 502 for garbage payload — that's fine).

**Important notes:**
- This is a live route change via Admin API — takes effect immediately, no pod restart needed
- The `PATCH` merges plugins — it won't remove existing plugins on the route
- UAT route IDs: `realtimewsprovider-vendor-jwt` (RTS), `rcm-injecting-jwt` (RCM) — PROD IDs may differ
- If PROD also has `apisix_delay_client_max_body_check on` in nginx.conf (check with `grep` inside the pod), the same fix applies

#### How to Apply the CSV Fix to PROD

In `PROD/backend/app/routers/metrics.py`, in the `export_traffic_report_csv` function:

1. Change the import line:
   ```python
   # Before:
   from app.services.traffic_report_service import get_traffic_report
   # After:
   from app.services.traffic_report_service import get_traffic_report, ROUTE_NAMES
   ```

2. Add route name resolution after the error check:
   ```python
   # Resolve friendly route name for CSV output
   route_display_name = ROUTE_NAMES.get(route_id, route_id)
   ```

3. Replace `route_id` with `route_display_name` in the `writer.writerow` call inside the for loop (the "Route" column).

4. Replace `route_id` with `route_display_name` in the filename:
   ```python
   filename = f"traffic_report_{route_display_name}_{date}.csv"
   ```


## Alert Rules — CLIENT_ERROR (4xx) Condition Type (June 2026)

### What It Does
New alert condition type that triggers when a route receives 4xx HTTP errors (400–499). Uses the same delta-based evaluation as UPSTREAM_ERROR — only alerts on NEW errors since the last evaluation cycle, not cumulative counts. Sends recovery when errors stop and healthy traffic resumes.

### Current Status
- **UAT**: Deployed to both backend and frontend ✅
- **PROD**: Deployed to both backend and frontend ✅

### How It Works
1. `ConditionType.CLIENT_ERROR` added to the enum in `schemas/notifications.py`
2. `evaluate_client_error()` in `metrics_evaluator.py` sums all 400–499 status codes
3. `_evaluate_metric_rule()` in `background_scheduler.py` uses high-water mark evaluation (same pattern as UPSTREAM_ERROR):
   - Tracks `__hwm_4xx__` per route (maximum 4xx count ever seen)
   - Alert triggers only when `current_4xx > hwm` (genuinely new errors)
   - Recovery triggers when no new 4xx above HWM AND healthy 2xx traffic flows
4. Email subject: `[ALERT] Client Error (4xx) - {route_name} ({route_id})`
5. Email body: dynamic breakdown table showing each 4xx code present (e.g. "404 Not Found: 5")

### Files Modified (both UAT and PROD)
| File | Change |
|------|--------|
| `backend/app/schemas/notifications.py` | Added `CLIENT_ERROR` to `ConditionType` enum and `COUNT_CONDITIONS` set |
| `backend/app/services/metrics_evaluator.py` | Added `evaluate_client_error()` function |
| `backend/app/services/background_scheduler.py` | Added CLIENT_ERROR delta-based evaluation block + import |
| `backend/app/services/smtp_dispatcher.py` | Added CLIENT_ERROR subject line + `_format_client_error_details()` helper |
| `frontend/src/components/AlertRuleForm.jsx` | Added `{ value: 'CLIENT_ERROR', label: 'Client Error (4xx)' }` to CONDITION_TYPES |

### Use Case
The RCM route on PROD was returning 404 errors from the vendor, but no alerts fired because only 5xx was monitored. With CLIENT_ERROR, any 4xx spike (404, 429, etc.) now triggers an email alert.

### How to Create a 4xx Alert Rule
1. Go to Notifications → Create Rule
2. Select the target route (e.g. "RCM - OAuth2")
3. Condition Type: **Client Error (4xx)**
4. Threshold: `1` (alert on any new 4xx error)
5. Set recipients and cooldown as desired


## Route Uptime Chart — Log Viewer Feature (June 2026)

### What It Does
Adds a visual **Response Time & Outage Detail** panel below the Log Viewer output. When logs are fetched for a route, the chart automatically appears showing:
- **Stats badges**: Uptime %, Avg Latency, Total Checks, OPERATIONAL/ERRORS status
- **Response Time chart**: Green area chart (recharts) showing per-request latency over time, with **red dots** marking error responses (4xx/5xx)
- **Outage Timeline bar**: Solid green for 2xx/3xx responses, switches to red for 4xx/5xx errors
- **Error Events table**: Lists each error occurrence with Time, Status code (red badge), HTTP Method, URI path, and Latency
- **Outage summary**: "No outages in this period" or "X error responses detected"

### Current Status
- **UAT**: Deployed to frontend ✅
- **PROD**: Deployed to frontend ✅ (July 2026)

### Known Issue — RESOLVED (July 2026)
The RouteUptimePanel date/time presets (Yesterday, Today, 1h–12h) were not correctly aligned with actual log data. **Fixed July 2026** — root causes and solutions:

| Root Cause | Fix |
|-----------|-----|
| `tail -20000` insufficient for "Yesterday" — today's traffic pushes yesterday's entries out of range | Historical queries use `tac` (reverse file read) + grep + head -10000, which reads from end of file and finds recent historical data immediately |
| Hour-based presets crossing midnight (e.g. 6h at 2 AM) only showed today from 00:00, losing yesterday's data | Frontend now fetches BOTH days in parallel and merges results |
| Manual `ts + timedelta(hours=2)` for SAST conversion was fragile | Replaced with proper `ts.astimezone(SAST)` using a `SAST = timezone(timedelta(hours=2))` constant |

**Files modified (UAT):**
- `backend/app/services/traffic_report_service.py` — added `SAST` constant, dynamic `tail_depth` based on `days_ago`, `astimezone(SAST)` conversion
- `frontend/src/components/RouteUptimePanel.jsx` — new `getDateAndTimeRanges()` returns array of ranges, `fetchMultiDayReport()` merges multi-day results

**How cross-midnight presets now work:**
1. `getDateAndTimeRanges('6h')` at 2:00 AM returns TWO ranges: `[{date: yesterday, timeFrom: '20:00', timeTo: '23:59'}, {date: today, timeFrom: '00:00', timeTo: '02:00'}]`
2. `fetchMultiDayReport()` fires both API calls in parallel via `Promise.all`
3. Minutes from earlier days are prefixed with `"MM-DD "` in the chart for visual distinction
4. Results are merged into a single `reportData` object with combined stats

**The bottom chart (RouteUptimeChart from raw log lines) works correctly** — it parses whatever log lines are fetched and shows accurate per-request data with red dots and error table.

### How It Works
- Parses the already-fetched JSON log lines from the Log Viewer (no extra API call)
- Extracts `start_time`, `response.status`, `latency`, `request.method`, and `request.uri` from each JSON log entry
- Only renders when logs contain parseable JSON entries (route-specific logs, not raw nginx format)
- Uses recharts `AreaChart` with gradient fill for the response time visualization
- **Red dots** on the chart mark error responses (4xx/5xx) so they stand out visually
- Timeline bar is built from computed segments (consecutive up/down periods)
- **Error Events table** below the timeline lists each error with Time, Status (red badge), Method, URI, and Latency

### Files Added/Modified (both UAT and PROD)
| File | Change |
|------|--------|
| `frontend/src/components/RouteUptimeChart.jsx` | **New file** — full chart component |
| `frontend/src/components/RouteUptimePanel.jsx` | Cross-midnight multi-day fetch + merge, `getDateAndTimeRanges()` function |
| `frontend/src/pages/Logs.jsx` | Import + render `RouteUptimeChart` and `RouteUptimePanel` below log output |
| `backend/app/services/traffic_report_service.py` | `SAST` constant, dynamic `tail_depth` with `tac` for historical queries, `astimezone(SAST)` |

### Frontend Build Tip
The `--from-dir=.` upload fails for the frontend because `node_modules` makes the archive too large. Always use the tar/`--from-archive` approach:
```bash
tar -czf build.tar.gz --exclude="node_modules" --exclude=".git" --exclude="src" -C <frontend-dir> .
oc start-build <build-name> --from-archive=build.tar.gz --follow -n <namespace>
```


## Keycloak PROD — Future Improvements (Identified June 2026 Go-Live)

These items were identified during the PROD go-live readiness check on 14 June 2026. They are non-blocking but should be addressed when time permits.

| Item | Current State | Recommended Fix | Priority |
|------|---------------|-----------------|----------|
| **Pin Keycloak image tag** | PROD uses `quay.io/keycloak/keycloak:latest` with `imagePullPolicy: Always` | Pin to a specific version (e.g. `26.4.6` to match the CronJob export image). Prevents unexpected upgrades on pod restart. | Medium |
| **Move DB credentials to K8s Secret** | `KC_DB_PASSWORD` and `POSTGRESQL_PASSWORD` are hardcoded in plain env vars in the Deployment spec | Create a K8s Secret (e.g. `keycloak-db-credentials`) and reference via `secretKeyRef` | Low (internal cluster only) |
| **Bootstrap admin password** | `KC_BOOTSTRAP_ADMIN_PASSWORD=admin123` visible in Deployment spec | Only used on first DB init so not a runtime risk. Can be removed from the Deployment after initial setup, or moved to a Secret. | Low |
| **Enable health + metrics flags in PROD** | PROD Keycloak args missing `--health-enabled=true` and `--metrics-enabled=true` (present in UAT template) | Add to PROD Deployment args. Health endpoints work by default in 26.x but explicit flags enable the full metrics endpoint for Prometheus scraping. | Low |
| **Update UAT deployment template namespace** | `keycloak-complete-deployment.yaml` in the workspace hardcodes `namespace: cro-apisix-uat` and UAT hostnames | Create a PROD version or parameterise the template so it can serve both environments | Low |

### How to Pin the Keycloak Image (When Ready)
```bash
oc login --token=<token> --server=https://api.prod-01-rb.ocp.fnb.co.za:6443
oc project cro-apisix-prod

# Patch the Deployment to pin the image
oc set image deployment/keycloak keycloak=quay.io/keycloak/keycloak:26.4.6 -n cro-apisix-prod

# Also set imagePullPolicy to IfNotPresent (avoids pulling on every restart)
oc patch deployment/keycloak -n cro-apisix-prod --type=json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"IfNotPresent"}]'

# Verify rollout
oc rollout status deployment/keycloak -n cro-apisix-prod --timeout=120s
```


## ControlM Escalation Feature (June 2026)

### What It Does
Automated phone-call escalation via ControlM when alert rules trigger and go unacknowledged. Writes trigger files to a configurable landing zone (network share) that ControlM's File Watcher detects. Critical monitors (real-time screening routes like RTS/Actimize) escalate immediately with 0 grace period.

### Current Status
- **UAT**: Feature deployed and ready for testing ✅
- **PROD**: Feature code present but **DO NOT deploy to PROD until UAT testing is complete**

### IMPORTANT: UAT-First Deployment Rule
**Do NOT modify PROD files for this feature until UAT testing confirms it works correctly.** The deployment sequence is:
1. Deploy to UAT (`cro-apisix-uat`)
2. Test trigger file generation, acknowledgment flow, settings UI
3. Verify with ControlM team that file format is acceptable
4. Only then deploy to PROD (`cro-apisix-prod`)

### Files Added (Both UAT and PROD)
| File | Purpose |
|------|---------|
| `backend/app/models/escalation_state.py` | Per-rule escalation lifecycle state |
| `backend/app/models/escalation_log.py` | Audit trail for escalation events |
| `backend/app/models/controlm_settings.py` | Singleton settings (enabled, landing zone, grace period) |
| `backend/app/services/controlm_escalation_service.py` | Decision logic, grace periods, acknowledgment |
| `backend/app/services/controlm_trigger_writer.py` | Atomic file writes to landing zone |
| `backend/app/routers/escalation.py` | 6 API endpoints for escalation management |
| `frontend/src/components/EscalationBadge.jsx` | Status badge (pending/escalated/critical) |
| `frontend/src/components/EscalationHistory.jsx` | Audit trail table with filters |

### Files Modified (Both UAT and PROD)
| File | Change |
|------|--------|
| `backend/app/models/alert_rule.py` | Added `notify_controlm` and `critical` columns |
| `backend/app/models/__init__.py` | Registered new models |
| `backend/app/main.py` | Added model imports, escalation router, startup restore |
| `backend/app/services/background_scheduler.py` | Wired escalation_service into evaluation cycle |
| `backend/app/services/notification_service.py` | Auto-default critical flag, pass controlm fields in CRUD |
| `backend/app/schemas/notifications.py` | Added notify_controlm/critical to schemas |
| `backend/app/routers/notifications.py` | Added fields to response helper |
| `frontend/src/components/AlertRuleForm.jsx` | Added ControlM section with toggles |
| `frontend/src/pages/Settings.jsx` | Added ControlM Escalation settings card |
| `frontend/src/pages/Notifications.jsx` | Integrated EscalationBadge + EscalationHistory |
| `frontend/src/api/notifications.js` | Updated JSDoc for new fields |

### Landing Zone Configuration
- **Current default**: `/app/data/controlm_alerts/` (writes locally on the pod's PVC)
- **Target**: Mount the ControlM landing zone NFS (`/mnt/landing_zone/mft/prod/incoming/croit/`) into the pod
- **Action needed**: Request infrastructure team to create PV/PVC for the NFS landing zone and mount into the backend deployment

### ControlM Team Request
Provide the ControlM team with this File Watcher specification:
```
FOLDER_NAME: CROITESCALATION
JOBNAME: CROIT_DASHBOARD_ALERT_FW
DESCRIPTION: Watch for CROIT escalation trigger files
TASKTYPE: File Watcher
FILE_PATH: /mnt/landing_zone/mft/prod/incoming/croit/  (or wherever the NFS mount lands)
FILE_NAME: CROIT_ALERT_*.trigger
SEARCH_INTERVAL: 1 minute (recommended for critical alerts)
BU_NAME: CRO IT Application Support
ONCE_FILE_FOUND: trigger phone call to 1st call / standby
```

### API Endpoints
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/escalation/settings` | admin | Get ControlM settings |
| PUT | `/api/escalation/settings` | admin | Update landing zone, grace period, global toggle |
| POST | `/api/escalation/acknowledge/{rule_id}` | admin, viewer | Acknowledge pending escalation |
| GET | `/api/escalation/status` | admin, viewer | Get all escalation statuses |
| GET | `/api/escalation/status/{rule_id}` | admin, viewer | Get single rule status |
| GET | `/api/escalation/history` | admin, viewer | Query escalation audit log |

### How to Deploy to UAT
```bash
# Backend
cd UAT/backend
python -m pytest tests/test_auth.py tests/test_proxy.py -v --tb=short
# If tests pass:
oc login --token=<token> --server=https://api.dev-02-rb.ocp.fnb.co.za:6443
oc project cro-apisix-uat
oc start-build apisix-dashboard-backend --from-dir=. --follow -n cro-apisix-uat
oc rollout restart deployment/apisix-dashboard-backend -n cro-apisix-uat

# Frontend
cd UAT/frontend
npx vite build
oc start-build apisix-dashboard-frontend --from-dir=. --follow -n cro-apisix-uat
oc rollout restart deployment/apisix-dashboard-frontend -n cro-apisix-uat
```

### How to Revert (if needed)
1. Remove the 3 new model files, 2 new service files, 1 new router file, 2 new frontend components
2. Revert modifications to the 11 files listed above (remove notify_controlm/critical columns, ControlM imports, escalation wiring)
3. Redeploy backend and frontend
