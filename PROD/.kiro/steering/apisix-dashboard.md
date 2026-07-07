# APISIX Dashboard — Project Knowledge Base

## Project Overview

CRO IT custom APISIX management dashboard deployed on OpenShift. Provides real-time route management, SSL certificate monitoring, pod metrics/health dashboards, and role-based access control for the FNB APISIX API gateway infrastructure.

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

### Frontend Architecture
- State: Zustand with `sessionStorage` persistence (`authStore.js`)
- API client: Axios with auto-attach Bearer token interceptor
- Session timeout: 30-minute inactivity auto-logout
- 401 interceptor: clears auth and redirects to `/login`

## OpenShift Deployment

### Cluster & Namespace
- **PROD cluster**: `https://api.prod-01-rb.ocp.fnb.co.za:6443`
- **Namespace**: `cro-apisix-prod`
- **Route**: `https://cro-apisix-croit-dashboard-prod.apps.prod-01-rb.ocp.fnb.co.za`

### Deployment Process (Backend Only — Most Common)
```bash
# 1. Login
oc login --token=<token> --server=https://api.prod-01-rb.ocp.fnb.co.za:6443
oc project cro-apisix-prod

# 2. Build & push (from backend/ directory)
oc start-build apisix-dashboard-backend --from-dir=. --follow -n cro-apisix-prod

# 3. Restart to pick up new image
oc rollout restart deployment/apisix-dashboard-backend -n cro-apisix-prod

# 4. Verify
oc rollout status deployment/apisix-dashboard-backend -n cro-apisix-prod
oc get pods -l component=backend -n cro-apisix-prod
```

### Deployment Process (Frontend)
```bash
# 1. Build frontend locally first
cd frontend
npx vite build

# 2. Then push (from frontend/ directory — needs dist/ present)
oc start-build apisix-dashboard-frontend --from-dir=. --follow -n cro-apisix-prod
oc rollout restart deployment/apisix-dashboard-frontend -n cro-apisix-prod
```

### Build Strategy
Both Dockerfiles use an **incremental overlay pattern**: they `FROM` the existing registry image and only COPY updated code on top. This avoids pulling base images from Docker Hub (rate limit issues) and keeps builds fast (~60s).

### Pod Health Checks
- **Liveness**: `GET /health` on port 8000 (backend), `GET /healthz` on port 8080 (frontend)
- **Readiness**: Same endpoints, shorter intervals
- **Note**: Backend startup can take 10-15s due to scheduler init + initial metrics fetch

### Image Registry
- Internal: `image-registry.openshift-image-registry.svc:5000/cro-apisix-prod/`
- Images: `apisix-dashboard-backend:1.0.0`, `apisix-dashboard-frontend:1.0.0`

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
1. **Service account bind** → search for user DN → bind as user (preferred when `LDAP_BIND_PASSWORD` is set correctly)
2. **Direct user bind** → `username@fnb.co.za` (fallback when service account fails)

If the service account password is wrong/placeholder, the code gracefully falls back to direct bind. This is where 2FA is triggered.

### Bug Fix History (June 2026)
**Problem**: Frontend "resets" after 2FA prompt appears
**Root cause**: `LDAP_HARD_TIMEOUT` was 8 seconds — too short for MFA round-trip. Timeout fired → returned None → 401 → axios interceptor cleared auth → redirect to login.
**Fix**: Increased all LDAP timeouts + added service account fallback to direct bind.

## Configuration

### Environment Variables
Config is loaded via pydantic-settings from `.env` file (local) or ConfigMap + Secret (OpenShift).

**Secrets** (in K8s Secret `apisix-dashboard-secrets`):
- `JWT_SECRET` — signing key for JWT tokens
- `APISIX_ADMIN_KEY` — APISIX Admin API key
- `LDAP_BIND_PASSWORD` — service account password

**ConfigMap** (`apisix-dashboard-config`): All non-sensitive settings including LDAP server, metrics URLs, SMTP config, etc.

### CORS
PROD CORS origin: `https://cro-apisix-croit-dashboard-prod.apps.prod-01-rb.ocp.fnb.co.za`

### Internal Service DNS (within cluster)
- Backend: `apisix-dashboard-backend.cro-apisix-prod.svc.cluster.local:8000`
- APISIX Admin: `apisix-admin-api.cro-apisix-prod.svc.cluster.local:9180`
- Metrics: `apisix-metrics.cro-apisix-prod.svc.cluster.local:9091`

## Testing

### Running Tests Locally
```bash
cd backend
python -m pytest tests/ -v --tb=short
```

### Test Setup Notes
- Tests use in-memory SQLite
- `conftest.py` sets env vars before importing app modules (avoids `.env` file conflicts)
- `APP_ENVIRONMENT` must be defined in `Settings` class (added June 2026 to support `.env` having this field)
- Hypothesis property tests have tight deadlines — flaky `DeadlineExceeded` errors are noise, not real failures

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Frontend resets on LDAP login | LDAP timeout too short for MFA | Increase `LDAP_HARD_TIMEOUT` to 60s |
| Pod crash-loops on deploy | Liveness probe fires before startup completes | Normal — pod recovers after 1-2 restarts; startup takes ~15s |
| `pydantic ValidationError: APP_ENVIRONMENT extra_forbidden` | `.env` has field not in Settings class | Add field to `Settings` with default |
| Tests fail with `extra_forbidden` | Same as above — tests load `.env` | Ensure all `.env` fields have matching Settings attributes |
| Service account bind fails | Placeholder password in `.env` | Code falls back to direct bind automatically |

## OC CLI Location
The `oc` binary is at: `PROD\oc\oc.exe` (relative to project root)
