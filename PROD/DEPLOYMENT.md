# APISIX Dashboard — Deployment Guide

## Architecture Overview

The application consists of two containers:

- **Backend** — Python/FastAPI serving the REST API on port 8000
- **Frontend** — React SPA built with Vite, served by nginx on port 8080 (also proxies `/api` to backend)

---

## Building Docker Images

### Backend

```bash
docker build -t apisix-dashboard-backend ./backend
```

### Frontend

```bash
docker build -t apisix-dashboard-frontend ./frontend
```

### Using Docker Compose (local development)

```bash
docker-compose up --build
```

This starts both services. The frontend is accessible at `http://localhost:8080`.

---

## Required Environment Variables (Production)

All sensitive configuration is read from environment variables. **No secrets are hardcoded.**

| Variable | Required | Description |
|----------|----------|-------------|
| `JWT_SECRET` | **Yes** | Secret key for signing JWT tokens. Use a strong random value (≥32 chars). |
| `APISIX_ADMIN_BASE_URL` | **Yes** | Base URL of the APISIX Admin API (e.g. `https://apisix-admin.internal:9180`). |
| `APISIX_ADMIN_KEY` | **Yes** | API key for authenticating with the APISIX Admin API. |
| `APISIX_METRICS_URL` | **Yes** | URL of the Prometheus metrics endpoint for APISIX pods. |
| `DATABASE_URL` | No | SQLAlchemy database URL. Defaults to `sqlite:///./apisix_dashboard.db`. |
| `JWT_ALGORITHM` | No | JWT signing algorithm. Defaults to `HS256`. |
| `JWT_EXPIRY_MINUTES` | No | Token expiry in minutes. Defaults to `30`. |
| `APISIX_ADMIN_VERIFY_SSL` | No | Whether to verify TLS certificates for Admin API calls. Defaults to `true`. |
| `APISIX_ADMIN_TIMEOUT` | No | Timeout in seconds for Admin API requests. Defaults to `10`. |
| `APISIX_METRICS_TIMEOUT` | No | Timeout in seconds for metrics requests. Defaults to `10`. |
| `CORS_ORIGINS` | No | Comma-separated list of allowed CORS origins. Defaults to `http://localhost:5173`. |
| `ROOT_PATH` | No | Root path prefix for reverse-proxy deployments (e.g. `/dashboard`). |
| `LOG_LEVEL` | No | Logging level. Defaults to `INFO`. |

### Example `.env` file

```env
JWT_SECRET=your-strong-random-secret-here
APISIX_ADMIN_BASE_URL=https://apisix-admin.internal:9180
APISIX_ADMIN_KEY=your-apisix-admin-api-key
APISIX_METRICS_URL=http://prometheus.monitoring:9090/api/v1/query
APISIX_ADMIN_VERIFY_SSL=true
DATABASE_URL=sqlite:///./apisix_dashboard.db
CORS_ORIGINS=https://dashboard.example.com
```

---

## Disabling TLS Verification (`APISIX_ADMIN_VERIFY_SSL`)

For internal OpenShift clusters that use self-signed certificates or internal CAs not in the system trust store, set:

```env
APISIX_ADMIN_VERIFY_SSL=false
```

This disables TLS certificate verification for all outbound requests from the backend to the APISIX Admin API. **Use this only in non-production environments or when the internal CA cannot be mounted into the container.**

For production, the recommended approach is to mount the internal CA certificate bundle:

```yaml
volumeMounts:
  - name: ca-bundle
    mountPath: /etc/ssl/certs/ca-certificates.crt
    subPath: ca-bundle.crt
volumes:
  - name: ca-bundle
    configMap:
      name: internal-ca-bundle
```

---

## OpenShift-Specific Notes

### Non-Root User

Both containers are configured to run as non-root users, which is required by OpenShift's default Security Context Constraints (SCC):

- **Backend**: Runs as UID `1001` with group `0` (root group for OpenShift compatibility)
- **Frontend**: Runs as the `nginx` user

OpenShift assigns arbitrary UIDs at runtime. The Dockerfiles set `g=u` permissions so that any UID in group `0` can read/write necessary files.

### Readiness and Liveness Probes

Configure probes in your DeploymentConfig or Deployment:

**Backend:**

```yaml
livenessProbe:
  httpGet:
    path: /api/docs
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /api/docs
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

**Frontend:**

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 3
  periodSeconds: 10
```

### Resource Limits

Recommended resource requests/limits:

```yaml
# Backend
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

# Frontend
resources:
  requests:
    cpu: 50m
    memory: 64Mi
  limits:
    cpu: 200m
    memory: 128Mi
```

### OpenShift Route

Expose the frontend service via an OpenShift Route with TLS edge termination:

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: apisix-dashboard
spec:
  to:
    kind: Service
    name: apisix-dashboard-frontend
  port:
    targetPort: 8080
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

### ConfigMap / Secret for Environment Variables

Store sensitive values in an OpenShift Secret:

```bash
oc create secret generic apisix-dashboard-secrets \
  --from-literal=JWT_SECRET='your-secret' \
  --from-literal=APISIX_ADMIN_KEY='your-admin-key'
```

Reference in the Deployment:

```yaml
envFrom:
  - secretRef:
      name: apisix-dashboard-secrets
  - configMapRef:
      name: apisix-dashboard-config
```

---

## Quick Start (Local Development)

```bash
# 1. Copy environment file
cp backend/.env.example backend/.env
# Edit backend/.env with your values

# 2. Start with Docker Compose
docker-compose up --build

# 3. Access the dashboard
open http://localhost:8080
```

Default admin credentials (first run only): `admin` / `N03ntry#`
