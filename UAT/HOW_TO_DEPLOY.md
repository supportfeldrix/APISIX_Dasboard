# APISIX Dashboard — How to Deploy to a New Server

This guide covers deploying the APISIX Dashboard application to a new environment, either locally (Docker/Podman) or on OpenShift.

---

## Prerequisites

| Requirement | Local | OpenShift |
|-------------|-------|-----------|
| Docker or Podman | Yes | No (builds in-cluster) |
| `oc` CLI | No | Yes |
| Access to APISIX Admin API | Yes | Yes |
| Network access to LDAP server | Optional | Optional |

---

## Project Structure

```
UAT/
├── backend/          # Python/FastAPI REST API
│   ├── app/          # Application source code
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/         # React SPA (Vite + Tailwind)
│   ├── src/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── deploy/           # OpenShift manifests and scripts
│   ├── openshift-deploy.yaml
│   ├── build-and-push.bat
│   └── build-on-openshift.bat
├── oc/               # oc CLI binary
└── docker-compose.yml
```

---

## PART 1: Local Deployment (Docker / Podman)

### Step 1: Clone or Copy the Project

Copy the entire `UAT/` folder to your new server.

### Step 2: Configure Environment Variables

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env` with your values:

```env
# REQUIRED — Generate a strong random string (32+ characters)
JWT_SECRET=your-strong-random-secret-minimum-32-characters

# REQUIRED — APISIX Admin API URL (the pod/container running APISIX)
APISIX_ADMIN_BASE_URL=https://your-apisix-host:9180

# REQUIRED — APISIX Admin API key (from your apisix config.yaml)
APISIX_ADMIN_KEY=your-apisix-admin-api-key

# REQUIRED — Prometheus metrics endpoint for APISIX
APISIX_METRICS_URL=http://your-prometheus:9091/apisix/prometheus/metrics

# Set to false if APISIX uses self-signed certs
APISIX_ADMIN_VERIFY_SSL=false

# LDAP Configuration (set LDAP_ENABLED=false to disable)
LDAP_ENABLED=true
LDAP_SERVER=ldaps://your-ldap-server:636
LDAP_BASE_DN=DC=your,DC=domain,DC=com
LDAP_USER_FILTER=(&(objectClass=user)(sAMAccountName={username}))
LDAP_BIND_DN=your-service-account@domain.com
LDAP_BIND_PASSWORD=your-bind-password
LDAP_USE_SSL=true
LDAP_VERIFY_SSL=false

# Database (SQLite — no setup needed)
DATABASE_URL=sqlite:///./apisix_dashboard.db

# CORS — set to your frontend URL
CORS_ORIGINS=http://localhost:8080

# Logging
LOG_LEVEL=INFO
```

### Step 3: Build and Start

Using Docker Compose:

```bash
cd UAT/
docker-compose up --build -d
```

Or using Podman:

```bash
cd UAT/
podman-compose up --build -d
```

### Step 4: Verify

```bash
# Check containers are running
docker ps

# Test backend health
curl http://localhost:8000/health

# Test frontend
curl http://localhost:8080/healthz
```

### Step 5: Access the Dashboard

Open `http://localhost:8080` in your browser.

Default login: `admin` / `N03ntry#`

### Step 6: Stop / Restart

```bash
# Stop
docker-compose down

# Restart
docker-compose up -d

# Rebuild after code changes
docker-compose up --build -d
```

### Notes for Local Deployment

- The SQLite database is stored in a Docker volume (`backend_data`). It persists across restarts.
- To reset the database, remove the volume: `docker volume rm uat_backend_data`
- The frontend nginx proxies `/api` requests to the backend container automatically.
- If LDAP is not available on your network, set `LDAP_ENABLED=false` in `.env`.

---

## PART 2: OpenShift Deployment

### Step 1: Login to OpenShift

```bash
oc login --token=<your-token> --server=https://api.<cluster-domain>:6443
oc project <your-namespace>
```

### Step 2: Create the Namespace (if needed)

```bash
oc new-project <your-namespace>
```

### Step 3: Update the Deployment Manifest

Edit `deploy/openshift-deploy.yaml` and update these values:

**ConfigMap (section 4):**

| Key | What to change |
|-----|----------------|
| `APISIX_ADMIN_BASE_URL` | Internal URL of your APISIX Admin API |
| `APISIX_METRICS_URL` | Internal URL of your Prometheus/metrics endpoint |
| `LDAP_SERVER` | Your LDAP server address |
| `LDAP_BIND_DN` | Your LDAP service account |
| `LDAP_BASE_DN` | Your LDAP base DN |
| `OC_API_SERVER` | Your OpenShift API server URL |
| `OC_NAMESPACE` | Your target namespace |
| `CORS_ORIGINS` | Your dashboard route URL |

**Secret (section 3):**

| Key | What to change |
|-----|----------------|
| `JWT_SECRET` | Generate a new strong random string (32+ chars) |
| `APISIX_ADMIN_KEY` | Your APISIX Admin API key |
| `LDAP_BIND_PASSWORD` | Your LDAP service account password |

**Route (section 10):**

| Key | What to change |
|-----|----------------|
| `spec.host` | Your desired dashboard hostname |

**PVC (section 5):**

| Key | What to change |
|-----|----------------|
| `spec.storageClassName` | Your cluster's storage class (check `oc get sc`) |

### Step 4: Create ImageStreams and BuildConfigs

```bash
oc create imagestream apisix-dashboard-backend -n <namespace>
oc create imagestream apisix-dashboard-frontend -n <namespace>

oc new-build --name=apisix-dashboard-backend --binary --strategy=docker \
  --to=apisix-dashboard-backend:1.0.0 -n <namespace>

oc new-build --name=apisix-dashboard-frontend --binary --strategy=docker \
  --to=apisix-dashboard-frontend:1.0.0 -n <namespace>
```

### Step 5: Build the Images

**Option A — Build on OpenShift (no local Docker needed):**

```bash
# Build backend
cd UAT/backend
oc start-build apisix-dashboard-backend --from-dir=. --follow -n <namespace>

# Build frontend
cd ../frontend
oc start-build apisix-dashboard-frontend --from-dir=. --follow -n <namespace>
```

**Option B — Build locally and push:**

```bash
# Login to the OpenShift registry
oc registry login --insecure=true

REGISTRY=default-route-openshift-image-registry.apps.<cluster-domain>
NAMESPACE=<your-namespace>

# Build and push backend
cd UAT/backend
docker build -t $REGISTRY/$NAMESPACE/apisix-dashboard-backend:1.0.0 .
docker push $REGISTRY/$NAMESPACE/apisix-dashboard-backend:1.0.0 --tls-verify=false

# Build and push frontend
cd ../frontend
docker build -t $REGISTRY/$NAMESPACE/apisix-dashboard-frontend:1.0.0 .
docker push $REGISTRY/$NAMESPACE/apisix-dashboard-frontend:1.0.0 --tls-verify=false
```

**Option C — Use the provided batch script (Windows):**

```cmd
cd UAT\deploy
build-on-openshift.bat
```

### Step 6: Apply the Deployment

```bash
oc apply -f deploy/openshift-deploy.yaml -n <namespace>
```

This creates:
- Service Account + RoleBinding
- Secret + ConfigMap
- PersistentVolumeClaim (1Gi for SQLite)
- Backend Deployment + Service
- Frontend Deployment + Service
- Route (HTTPS with TLS edge termination)

### Step 7: Create the Service Account Token

The backend needs a token to query the Kubernetes API for pod info:

```bash
oc create token apisix-dashboard-sa -n <namespace> --duration=8760h
```

Patch the secret with the token:

```bash
oc patch secret apisix-dashboard-secrets -n <namespace> \
  --type merge -p '{"stringData":{"OC_TOKEN":"<paste-token-here>"}}'
```

Then restart the backend to pick it up:

```bash
oc rollout restart deployment/apisix-dashboard-backend -n <namespace>
```

### Step 8: Verify

```bash
# Check pods are running
oc get pods -l app=apisix-dashboard -n <namespace>

# Check the route
oc get route -l app=apisix-dashboard -n <namespace>

# Test health endpoint
curl -k https://<your-route-hostname>/healthz
```

### Step 9: Login

Open `https://<your-route-hostname>` in your browser.

- First login: `admin` / `N03ntry#`
- LDAP users: Use your domain credentials (auto-created as viewer on first login)

---

## Updating After Code Changes

### Local

```bash
cd UAT/
docker-compose up --build -d
```

### OpenShift — Frontend only

```bash
cd UAT/frontend
oc start-build apisix-dashboard-frontend --from-dir=. --follow -n <namespace>
oc rollout restart deployment/apisix-dashboard-frontend -n <namespace>
```

### OpenShift — Backend only

```bash
cd UAT/backend
oc start-build apisix-dashboard-backend --from-dir=. --follow -n <namespace>
oc rollout restart deployment/apisix-dashboard-backend -n <namespace>
```

### OpenShift — Both

```bash
cd UAT/deploy
build-on-openshift.bat
oc rollout restart deployment/apisix-dashboard-backend -n <namespace>
oc rollout restart deployment/apisix-dashboard-frontend -n <namespace>
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| 504 Gateway Timeout on login | LDAP server unreachable from pod. Check network policies. Set `LDAP_ENABLED=false` to disable. |
| "APISIX Admin API unreachable" | Wrong `APISIX_ADMIN_BASE_URL`. Check the internal DNS or pod IP. |
| Backend pod CrashLoopBackOff | Check logs: `oc logs deploy/apisix-dashboard-backend`. Usually a missing env var. |
| Frontend shows blank page | Check browser console. Likely a CORS issue — update `CORS_ORIGINS`. |
| Login works but routes show empty | APISIX Admin API key is wrong. Verify `APISIX_ADMIN_KEY` matches your APISIX config. |
| "Insufficient permissions" | You're logged in as a viewer. Ask an admin to promote your role. |
| SQLite locked errors | Only 1 backend replica is supported with SQLite. Don't scale beyond 1. |
| Pod metrics not showing | SA token expired. Recreate with `oc create token apisix-dashboard-sa`. |

---

## Backup and Restore

### Export the SQLite Database

```bash
# Local
docker cp apisix-dashboard-backend:/app/data/apisix_dashboard.db ./backup.db

# OpenShift
oc cp <backend-pod-name>:/app/data/apisix_dashboard.db ./backup.db -n <namespace>
```

### Restore

```bash
# Local
docker cp ./backup.db apisix-dashboard-backend:/app/data/apisix_dashboard.db
docker restart apisix-dashboard-backend

# OpenShift
oc cp ./backup.db <backend-pod-name>:/app/data/apisix_dashboard.db -n <namespace>
oc rollout restart deployment/apisix-dashboard-backend -n <namespace>
```

---

## Security Checklist

- [ ] Change `JWT_SECRET` to a unique random value (never reuse across environments)
- [ ] Change the default admin password after first login
- [ ] Set `APISIX_ADMIN_VERIFY_SSL=true` in production (mount CA bundle if needed)
- [ ] Restrict network policies to only allow frontend → backend → APISIX traffic
- [ ] Set `LDAP_VERIFY_SSL=true` in production if your LDAP cert is trusted
- [ ] Review CORS_ORIGINS — only allow your actual dashboard URL
- [ ] Rotate the SA token periodically (it expires based on `--duration`)

---

## Architecture Diagram

```
User Browser
     │
     ▼ (HTTPS, port 443)
┌──────────────────────────────────────┐
│  Route / Reverse Proxy (TLS edge)    │
└──────────────────┬───────────────────┘
                   │
                   ▼ (port 8080)
┌──────────────────────────────────────┐
│  Frontend Container (nginx)          │
│  • Serves React SPA static files     │
│  • Proxies /api → backend:8000       │
└──────────────────┬───────────────────┘
                   │
                   ▼ (port 8000)
┌──────────────────────────────────────┐
│  Backend Container (FastAPI/Uvicorn)  │
│  • JWT Authentication                │
│  • LDAP Integration (optional)       │
│  • Proxy to APISIX Admin API         │
│  • Audit Logging (SQLite)            │
│  • Metrics from Prometheus           │
│  • Pod info from K8s API             │
└───┬──────────┬──────────┬────────────┘
    │          │          │
    ▼          ▼          ▼
 APISIX     LDAP       K8s API
 Admin      Server     (optional)
 :9180      :636       :6443
```

---

## Ports Reference

| Service | Port | Protocol |
|---------|------|----------|
| Frontend (nginx) | 8080 | HTTP |
| Backend (uvicorn) | 8000 | HTTP |
| APISIX Admin API | 9180 | HTTP/HTTPS |
| APISIX Metrics | 9091 | HTTP |
| LDAP | 636 | LDAPS |
| OpenShift API | 6443 | HTTPS |

---

*Document created: 2026-05-13 | CRO IT — APISIX Dashboard v1.0.0*
