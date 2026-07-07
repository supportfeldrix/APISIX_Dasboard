# OpenShift Deployment Guide

## Quick Deploy

### Step 1: Build the images

From your laptop (with Docker/Podman installed):

```bash
# Login to OpenShift
oc login --token=<your-token> --server=https://api.dev-02-rb.ocp.fnb.co.za:6443

# Login to the internal registry
oc registry login

# Build and push backend
cd backend
docker build -t default-route-openshift-image-registry.apps.dev-02-rb.ocp.fnb.co.za/cro-apisix-uat/apisix-dashboard-backend:1.0.0 .
docker push default-route-openshift-image-registry.apps.dev-02-rb.ocp.fnb.co.za/cro-apisix-uat/apisix-dashboard-backend:1.0.0

# Build and push frontend
cd ../frontend
docker build -t default-route-openshift-image-registry.apps.dev-02-rb.ocp.fnb.co.za/cro-apisix-uat/apisix-dashboard-frontend:1.0.0 .
docker push default-route-openshift-image-registry.apps.dev-02-rb.ocp.fnb.co.za/cro-apisix-uat/apisix-dashboard-frontend:1.0.0
```

### Step 2: Update the Secret

Before applying, edit `openshift-deploy.yaml` and change:
- `JWT_SECRET` → a strong random string (32+ characters)
- Verify `APISIX_ADMIN_KEY` matches your APISIX config
- Verify `LDAP_BIND_PASSWORD` is correct

### Step 3: Fix the APISIX Admin URL

The `APISIX_ADMIN_BASE_URL` in the ConfigMap needs to point to your APISIX pod's Admin API.
Check the correct internal DNS:

```bash
# Find the headless service for your StatefulSet
oc get svc -n cro-apisix-uat | grep -i headless

# The URL format is: http://<pod-name>.<headless-svc>.<namespace>.svc.cluster.local:<port>
# Example: http://apisix-uat-0.apisix-headless.cro-apisix-uat.svc.cluster.local:9180
```

If there's no headless service, use the pod IP directly or create one.

### Step 4: Set up the Service Account token

```bash
# After applying the YAML, get the SA token:
oc create token apisix-dashboard-sa -n cro-apisix-uat --duration=8760h

# Then patch the secret with the token:
oc patch secret apisix-dashboard-secrets -n cro-apisix-uat \
  --type merge -p '{"stringData":{"OC_TOKEN":"<paste-token-here>"}}'
```

### Step 5: Apply everything

```bash
oc apply -f openshift-deploy.yaml -n cro-apisix-uat
```

### Step 6: Verify

```bash
# Check pods are running
oc get pods -l app=apisix-dashboard -n cro-apisix-uat

# Check the route
oc get route apisix-admin-ui -n cro-apisix-uat

# Test the URL
curl -k https://cro-apisix-admin-ui-uat.apps.dev-02-rb.ocp.fnb.co.za/healthz
```

### Step 7: Login

Open: https://cro-apisix-admin-ui-uat.apps.dev-02-rb.ocp.fnb.co.za

Login with:
- Your FNB LDAP credentials (first login creates you as viewer)
- Or `admin` / `N03ntry#` (local admin account)

---

## Architecture on OpenShift

```
Internet/Intranet
       │
       ▼ (port 443, TLS edge)
┌─────────────────────────────────────────┐
│  Route: cro-apisix-admin-ui-uat.apps... │
└─────────────────┬───────────────────────┘
                  │
                  ▼ (port 8080)
┌─────────────────────────────────────────┐
│  Frontend Pod (nginx)                    │
│  - Serves React SPA                      │
│  - Proxies /api → backend:8000           │
└─────────────────┬───────────────────────┘
                  │
                  ▼ (port 8000)
┌─────────────────────────────────────────┐
│  Backend Pod (uvicorn/FastAPI)           │
│  - Auth (JWT + LDAP)                     │
│  - Proxy to APISIX Admin API            │
│  - Metrics from Prometheus              │
│  - Pod info from K8s API                │
│  - SQLite DB on PVC                     │
└────┬────────────┬───────────────┬───────┘
     │            │               │
     ▼            ▼               ▼
  APISIX       APISIX         K8s API
  Admin:9180   Metrics:9091   :6443
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Frontend shows "502" | Backend pod not ready. Check `oc logs deploy/apisix-dashboard-backend` |
| "APISIX Admin API unreachable" | Wrong `APISIX_ADMIN_BASE_URL`. Check internal DNS. |
| LDAP login fails | Check `LDAP_SERVER` is reachable from the pod. Try `oc exec` + `curl`. |
| Pod metrics empty | SA token expired or missing. Recreate with `oc create token`. |
| Route not accessible | Check `oc get route` and DNS resolution. |
