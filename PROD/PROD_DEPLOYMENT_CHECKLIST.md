# APISIX Dashboard — PRODUCTION Deployment Checklist

## Pre-Deployment: Values to Gather

Before deploying, you need these values from your PROD environment:

| # | Item | Where to find it | Example (UAT) |
|---|------|-------------------|---------------|
| 1 | **PROD Namespace** | `oc get projects` | `cro-apisix-prod` |
| 2 | **APISIX Admin API URL** | Internal pod IP or service DNS | `http://192.168.x.x:9180` |
| 3 | **APISIX Admin API Key** | APISIX config.yaml | `TyqjNqbWXKbmHOVGYtPfptUOXDWIGyAA` |
| 4 | **Prometheus Metrics URL** | Service DNS in namespace | `http://apisix-metrics.NS.svc.cluster.local:9091/apisix/prometheus/metrics` |
| 5 | **APISIX Pod Names** | `oc get pods` in PROD | `apisix-prod-0`, `apisix-prod-1` |
| 6 | **Dashboard Route Hostname** | Your choice | `cro-apisix-croit-dashboard-prod.apps.CLUSTER.DOMAIN` |
| 7 | **OpenShift API Server** | Cluster info | `https://api.CLUSTER.DOMAIN:6443` |
| 8 | **LDAP Bind Password** | Same as UAT or different | `InwxvJ.NWkaYf*1s` |
| 9 | **Storage Class** | `oc get sc` | `dorado-nfs-csi` |

---

## Step 1: Update Configuration Files

### Files to update (search for `CHANGE-ME`):

1. **`backend/.env`** — All `CHANGE-ME-*` values
2. **`deploy/openshift-deploy.yaml`** — All `CHANGE-ME-*` values
3. **`backend/app/services/traffic_report_service.py`** — APISIX pod names (line ~24)

### Quick find all placeholders:
```bash
grep -rn "CHANGE-ME" .
```

---

## Step 2: Build Frontend Locally

```bash
cd frontend
npm install
npx vite build
```

---

## Step 3: Login to PROD OpenShift

```bash
oc login --token=<your-token> --server=https://api.CLUSTER.DOMAIN:6443
oc project <PROD-NAMESPACE>
```

---

## Step 4: Create ImageStreams and BuildConfigs

```bash
oc create imagestream apisix-dashboard-backend -n <NAMESPACE>
oc create imagestream apisix-dashboard-frontend -n <NAMESPACE>
oc new-build --name=apisix-dashboard-backend --binary --strategy=docker --to=apisix-dashboard-backend:1.0.0 -n <NAMESPACE>
oc new-build --name=apisix-dashboard-frontend --binary --strategy=docker --to=apisix-dashboard-frontend:1.0.0 -n <NAMESPACE>
```

---

## Step 5: Build and Push Images

```bash
# Backend
cd backend
oc start-build apisix-dashboard-backend --from-dir=. --follow -n <NAMESPACE>

# Frontend (uses pre-built dist/)
cd ../frontend
oc start-build apisix-dashboard-frontend --from-dir=. --follow -n <NAMESPACE>
```

---

## Step 6: Apply Deployment Manifest

```bash
oc apply -f deploy/openshift-deploy.yaml -n <NAMESPACE>
```

---

## Step 7: Create RBAC for Pod Management

```bash
# Allow dashboard to delete pods (restart feature)
oc create role pod-manager --verb=delete --resource=pods -n <NAMESPACE>
oc create rolebinding apisix-dashboard-pod-manager --role=pod-manager --serviceaccount=<NAMESPACE>:apisix-dashboard-sa -n <NAMESPACE>

# Allow dashboard to exec into APISIX pods (traffic report)
oc create role pod-exec --verb=create,get --resource=pods/exec -n <NAMESPACE>
oc create rolebinding apisix-dashboard-pod-exec --role=pod-exec --serviceaccount=<NAMESPACE>:apisix-dashboard-sa -n <NAMESPACE>
```

---

## Step 8: Enable Prometheus Plugin on Routes

Run this from inside the backend pod (or use the UAT script as reference):
```bash
oc exec deployment/apisix-dashboard-backend -n <NAMESPACE> -- python /app/enable_prometheus_plugin.py
```

Or manually enable the `prometheus` plugin with `prefer_name: true` on each APISIX route.

---

## Step 9: Verify

```bash
# Check pods
oc get pods -l app=apisix-dashboard -n <NAMESPACE>

# Check route
oc get route -l app=apisix-dashboard -n <NAMESPACE>

# Test health
curl -k https://<DASHBOARD-HOSTNAME>/health
```

---

## Step 10: First Login

- URL: `https://<DASHBOARD-HOSTNAME>`
- Default: `admin` / `N03ntry#`
- Change the admin password immediately after first login

---

## Key Differences from UAT

| Setting | UAT | PROD |
|---------|-----|------|
| Namespace | `cro-apisix-uat` | `<your-prod-namespace>` |
| APISIX pods | `apisix-uat-0/1` | `apisix-prod-0/1` (update in traffic_report_service.py) |
| JWT_SECRET | shared dev secret | **unique strong secret** |
| LOG_LEVEL | INFO | INFO (or WARN for less noise) |
| Dashboard hostname | `cro-apisix-croit-dashboard-uat.apps...` | Your PROD hostname |

---

## Security Reminders

- [ ] Generate a **unique** JWT_SECRET (never reuse UAT value)
- [ ] Change default admin password after first login
- [ ] Verify CORS_ORIGINS only allows the PROD dashboard URL
- [ ] Confirm LDAP is working for user authentication
- [ ] Test the "Test Email" button to verify SMTP connectivity (if firewall allows)

---

*Created: 2026-05-15 | CRO IT — APISIX Dashboard PROD Setup*
