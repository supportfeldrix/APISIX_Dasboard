# APISIX Dashboard (UAT) — Project Knowledge Base

## Project Overview

CRO IT custom APISIX management dashboard — **UAT environment**. This is the testing/staging instance used for validating changes before promoting to PROD. Provides real-time route management, SSL certificate monitoring, pod metrics/health dashboards, and role-based access control for the FNB APISIX API gateway infrastructure.

## Architecture

### Stack
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy (SQLite on PVC), uvicorn
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

## OpenShift Deployment (UAT)

### Cluster & Namespace
- **UAT cluster**: `https://api.dev-02-rb.ocp.fnb.co.za:6443`
- **Namespace**: `cro-apisix-uat`
- **Route**: `https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb.ocp.fnb.co.za`
- **External registry**: `default-route-openshift-image-registry.apps.dev-02-rb.ocp.fnb.co.za`

### Deployment Process (Backend Only — Most Common)
```bash
# 1. Login
oc login --token=<token> --server=https://api.dev-02-rb.ocp.fnb.co.za:6443
oc project cro-apisix-uat

# 2. Build & push (from backend/ directory)
oc start-build apisix-dashboard-backend --from-dir=. --follow -n cro-apisix-uat

# 3. Restart to pick up new image
oc rollout restart deployment/apisix-dashboard-backend -n cro-apisix-uat

# 4. Verify
oc rollout status deployment/apisix-dashboard-backend -n cro-apisix-uat
oc get pods -l component=backend -n cro-apisix-uat
```

### Deployment Process (Frontend)
```bash
# 1. Build frontend locally first
cd frontend
npx vite build

# 2. Then push (from frontend/ directory — needs dist/ present)
oc start-build apisix-dashboard-frontend --from-dir=. --follow -n cro-apisix-uat
oc rollout restart deployment/apisix-dashboard-frontend -n cro-apisix-uat
```

### Full Deploy (Both Components)
Use the batch scripts:
- `deploy/build-on-openshift.bat` — builds both images on-cluster (no local Docker needed)
- `deploy/build-and-push.bat` — builds locally with Podman/Docker then pushes

### Build Strategy
Both Dockerfiles use an **incremental overlay pattern**: they `FROM` the existing registry image and only COPY updated code on top. This avoids pulling base images from Docker Hub (rate limit issues) and keeps builds fast (~60s).

### Pod Health Checks
- **Liveness**: `GET /health` on port 8000 (backend), `GET /healthz` on port 8080 (frontend)
- **Readiness**: Same endpoints, shorter intervals
- **Note**: Backend startup can take 10-15s due to scheduler init + initial metrics fetch. 1-2 restart cycles on deploy is normal.

### Image Registry
- Internal: `image-registry.openshift-image-registry.svc:5000/cro-apisix-uat/`
- Images: `apisix-dashboard-backend:1.0.0`, `apisix-dashboard-frontend:1.0.0`

## UAT vs PROD Differences

| Setting | UAT | PROD |
|---------|-----|------|
| Cluster | `api.dev-02-rb.ocp.fnb.co.za` | `api.prod-01-rb.ocp.fnb.co.za` |
| Namespace | `cro-apisix-uat` | `cro-apisix-prod` |
| APISIX Admin URL | `http://192.168.84.90:9180` (direct pod IP) | Service DNS (`apisix-admin-api.cro-apisix-prod.svc`) |
| CORS Origin | `https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb...` | `https://cro-apisix-croit-dashboard-prod.apps.prod-01-rb...` |
| Local dev APISIX | `http://localhost:9180` | N/A |
| APP_ENVIRONMENT | `UAT` | `PROD` |

**Important**: UAT uses a direct pod IP (`192.168.84.90`) for APISIX Admin because the `apisix-dashboard` service returns 403 due to `allow_admin` restrictions. If APISIX pods restart, this IP will change and needs updating in the ConfigMap.

## LDAP Authentication — Lessons Learned

### How It Works
1. User enters AD credentials on login page
2. Backend tries local DB auth first (fast path)
3. If not local user → LDAP bind against `ldaps://ldap.fnbconnect.co.za:636`
4. FNB AD triggers **2FA/MFA push notification** on user's phone during LDAP bind
5. User approves MFA → bind succeeds → JWT issued
6. LDAP users are auto-created in local DB on first login (viewer role by default)

### Critical Timeout Configuration
The LDAP bind triggers a corporate MFA challenge that can take 15-30 seconds for user approval. All timeouts must accommodate this:

| Setting | Value | Why |
|---------|-------|-----|
| `LDAP_HARD_TIMEOUT` | 60s | ThreadPoolExecutor timeout wrapping the entire LDAP operation |
| `receive_timeout` | 55s | ldap3 Connection socket timeout (must be < hard timeout) |
| `connect_timeout` | 5s | Initial TCP connection to LDAP server (no MFA involved) |
| `proxy_read_timeout` (nginx) | 60s | Nginx waiting for backend response |

### Service Account Fallback
The code has two auth paths:
1. **Service account bind** → search for user DN → bind as user (preferred when `LDAP_BIND_PASSWORD` is correct)
2. **Direct user bind** → `username@fnb.co.za` (fallback when service account fails)

If the service account password is wrong/expired, the code gracefully falls back to direct bind. This is where 2FA gets triggered.

### Bug Fix History (June 2026)
**Problem**: Frontend "resets" after 2FA prompt — user can't log in
**Root cause**: `LDAP_HARD_TIMEOUT` was originally 8 seconds — too short for MFA push notification round-trip. Timeout fired → returned None → 401 → axios interceptor cleared auth → redirect to login.
**Fix**: Increased all LDAP timeouts to 60/55s + added service account bind fallback to direct user bind.

## Configuration

### Environment Variables
Config is loaded via pydantic-settings from `.env` file (local) or ConfigMap + Secret (OpenShift).

**Secrets** (in K8s Secret `apisix-dashboard-secrets`):
- `JWT_SECRET` — signing key for JWT tokens
- `APISIX_ADMIN_KEY` — APISIX Admin API key
- `LDAP_BIND_PASSWORD` — LDAP service account password

**ConfigMap** (`apisix-dashboard-config`): All non-sensitive settings including LDAP server, metrics URLs, SMTP config, etc.

### CORS
- Local dev: `http://localhost:5173`
- UAT cluster: `https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb.ocp.fnb.co.za`

### Internal Service DNS (within UAT cluster)
- Backend: `apisix-dashboard-backend.cro-apisix-uat.svc.cluster.local:8000`
- APISIX Metrics: `apisix-metrics.cro-apisix-uat.svc.cluster.local:9091`

### Local Development
```bash
# Terminal 1 — Backend
cd backend
python run.py
# Runs on http://localhost:8000

# Terminal 2 — Frontend
cd frontend
npm run dev
# Runs on http://localhost:5173 (Vite dev server)
```

The local `.env` file points to `localhost` for APISIX Admin and Metrics. The `start-local.bat` or `start_all.bat` scripts can start both services.

## Testing

### Running Tests Locally
```bash
cd backend
python -m pytest tests/ -v --tb=short
```

### Test Setup Notes
- Tests use in-memory SQLite
- `conftest.py` sets env vars before importing app modules (avoids `.env` file conflicts)
- `APP_ENVIRONMENT` must be defined in `Settings` class if `.env` contains it
- Hypothesis property tests have tight deadlines — flaky `DeadlineExceeded` errors are noise, not real failures
- Additional test scripts: `test_traffic.py`, `test_parse.py`, `check_routes.py` (standalone scripts, not pytest)

### Utility Scripts
- `enable_prometheus_plugin.py` — enables the prometheus plugin on APISIX routes
- `check_routes.py` — validates APISIX route configuration

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Frontend resets on LDAP login | LDAP timeout too short for MFA | Ensure `LDAP_HARD_TIMEOUT` is 60s |
| Pod crash-loops on deploy | Liveness probe fires before startup completes | Normal — pod recovers after 1-2 restarts |
| APISIX Admin returns 403 | `allow_admin` config restricts source IPs | Use direct pod IP in `APISIX_ADMIN_BASE_URL` |
| APISIX Admin 403 after pod restart | Pod IP changed | Update ConfigMap with new pod IP, restart backend |
| `pydantic ValidationError: extra_forbidden` | `.env` has field not in Settings class | Add field to `Settings` with default |
| CORS errors in browser | Route URL doesn't match `CORS_ORIGINS` | Update ConfigMap and restart |

## Promoting UAT → PROD

When changes are tested and ready for production:
1. Ensure the same code changes are applied to the PROD folder (both folders maintain separate copies)
2. Login to PROD cluster: `oc login --server=https://api.prod-01-rb.ocp.fnb.co.za:6443`
3. Follow the same build/deploy process targeting `cro-apisix-prod` namespace
4. Verify via PROD route

## OC CLI Location
The `oc` binary is at: `UAT\oc\oc.exe` (relative to project root)
