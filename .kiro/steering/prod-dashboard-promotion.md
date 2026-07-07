---
inclusion: manual
---

# APISIX Dashboard — PROD Promotion Guide

## Purpose

This steering document covers promoting UAT-tested dashboard features to PROD. It includes the alert system fixes, Log Viewer charts, the CLIENT_ERROR frontend condition type, and the Prometheus metrics parser fix. Follow the sections in order — backend first, then frontend.

## UAT Testing Summary (1 July 2026)

During UAT testing, four bugs were discovered and fixed that would also affect PROD:

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| CLIENT_ERROR alerts never fire | Shared `_previous_metrics` key collision between UPSTREAM_ERROR and CLIENT_ERROR for same route | Use dedicated `__client_error__` prefixed key |
| Metrics parser returns empty dict | `line.split(" ")` breaks when route names contain spaces (e.g. "RTS - OAuth2 - Secure") | Use `line.rfind("}")` to split labels from value |
| False positive alerts (pod load-balancing) | Metrics service round-robins between 2 APISIX pods with different counters — alternating creates fake deltas | High-water mark (HWM) approach: only alert when count exceeds historical maximum |
| Pod recreation not detected | Evaluator only checked `restartCount`; StatefulSet rolling update creates new pod with count=0 | Track pod `startTime` between cycles |

---

## What Needs Promoting

| Feature | Backend | Frontend | Status in PROD |
|---------|---------|----------|----------------|
| CLIENT_ERROR (4xx) alerts — full fix | ⚠️ Needs HWM + parser fix | ⚠️ Missing from Notifications.jsx | Not working correctly |
| Prometheus parser (spaces in route names) | ⚠️ Not yet applied | N/A | Parser returns empty — all metric alerts broken |
| Pod recreation detection | ✅ Already deployed | N/A | Working |
| Route Uptime Chart (Log Viewer) | N/A (frontend-only) | ⚠️ Missing entirely | Not deployed |
| Route Uptime Panel (time presets) | ⚠️ traffic_report_service.py needs SAST fix | ⚠️ Missing entirely | Not deployed |
| Evaluation interval (10s) | ⚠️ ConfigMap still 60s | N/A | Working but slow |

**Critical note:** The Prometheus parser fix affects ALL metric-based alerts (UPSTREAM_ERROR, CLIENT_ERROR, JWT_FAILURE, HIGH_ERROR_RATE). Without it, no metric alerts will fire on PROD either — if PROD routes have spaces in their names, the parser returns an empty dict.

---

## Part 1: Backend Changes

### Step 1.1 — Fix Prometheus Metrics Parser (CRITICAL)

This fix is required for ALL metric-based alerts to work. Without it, route names with spaces (like "RCM - OAuth2") break the parser.

In `PROD/backend/app/services/metrics_evaluator.py`, replace the `parse_route_status_metrics` function. The key change is replacing `line.split(" ")` with `line.rfind("}")`:

**Find and replace the entire function** with the version from UAT:
```
Copy UAT/backend/app/services/metrics_evaluator.py → PROD/backend/app/services/metrics_evaluator.py
```

Or manually change these lines in the function:

**Remove:**
```python
        parts = line.split(" ")
        if len(parts) < 2:
            continue

        metric_part = parts[0]
        try:
            value = float(parts[-1])
        except ValueError:
            continue
```

**Replace with:**
```python
        # Split on closing brace to separate metric labels from value.
        # Cannot use split(" ") because route names contain spaces.
        brace_idx = line.rfind("}")
        if brace_idx < 0:
            continue

        metric_part = line[: brace_idx + 1]
        value_part = line[brace_idx + 1 :].strip()

        try:
            value = float(value_part)
        except ValueError:
            continue
```

### Step 1.2 — Fix CLIENT_ERROR Evaluation (HWM Approach)

The CLIENT_ERROR block in `_evaluate_metric_rule()` needs a full replacement. The simplest approach:

```
Copy UAT/backend/app/services/background_scheduler.py → PROD/backend/app/services/background_scheduler.py
```

If copying the full file, verify:
- `_previous_pod_starts` is in `__init__` ✓ (already applied)
- `_evaluate_pod_health` uses the tuple return ✓ (already applied)
- CLIENT_ERROR block uses HWM approach (new)
- `METRIC_RULE` debug logging is present (helpful for PROD debugging)

**Key changes in the CLIENT_ERROR block:**
- Uses `__client_error__` prefixed key (avoids UPSTREAM_ERROR collision)
- Tracks a high-water mark (`__hwm_4xx__`) instead of raw previous count
- Delta is `current_4xx - hwm` (only positive when genuinely new errors occur)
- HWM never decreases — immune to pod load-balancing fluctuation
- Recovery checks `current_2xx > 0` (traffic flowing)

### Step 1.3 — Update traffic_report_service.py (SAST + Dynamic Tail Depth)

```
Copy UAT/backend/app/services/traffic_report_service.py → PROD/backend/app/services/traffic_report_service.py
```

Key changes:
- `SAST = timezone(timedelta(hours=2))` constant
- `ts.astimezone(SAST)` instead of `ts + timedelta(hours=2)`
- Dynamic `tail_depth` (20k/100k/200k based on `days_ago`)
- Historical queries use `tac` for performance

### Step 1.4 — Update ConfigMap (Evaluation Interval)

```bash
oc login --token=<TOKEN> --server=https://api.prod-01-rb.ocp.fnb.co.za:6443
oc project cro-apisix-prod

# Set evaluation interval to 10 seconds for real-time screening detection
oc patch configmap apisix-dashboard-config -n cro-apisix-prod \
  --type=merge -p '{"data":{"NOTIFICATION_EVAL_INTERVAL":"10"}}'
```

### Step 1.5 — Deploy Backend

```bash
cd PROD/backend
python -m pytest tests/test_auth.py tests/test_proxy.py tests/test_yaml_converter.py -v --tb=short

# Only deploy if tests pass:
oc start-build apisix-dashboard-backend --from-dir=. --follow -n cro-apisix-prod
oc rollout restart deployment/apisix-dashboard-backend -n cro-apisix-prod
oc rollout status deployment/apisix-dashboard-backend -n cro-apisix-prod
```

### Step 1.6 — Verify Backend

```bash
oc get pods -l component=backend -n cro-apisix-prod
# Should show 1/1 Running, 0 restarts

oc logs -l component=backend -n cro-apisix-prod --tail=15
# Should show:
#   "Notification scheduler started (interval=10s)."
#   "[METRIC_RULE] rule='...' ... found_in_metrics=True"  (confirms parser works)
```

**Important:** On the first evaluation cycle after startup, the HWM will be set from 0 to the current counter value. This means one initial alert email will fire (capturing existing cumulative errors as "new"). This is expected and normal — after that single email, alerts only fire for genuinely new errors.

---

## Part 2: Frontend Changes

### Step 2.1 — Copy New Components from UAT

```
UAT/frontend/src/components/RouteUptimeChart.jsx → PROD/frontend/src/components/RouteUptimeChart.jsx
UAT/frontend/src/components/RouteUptimePanel.jsx → PROD/frontend/src/components/RouteUptimePanel.jsx
```

These are new files — no conflict with existing PROD files.

### Step 2.2 — Update Logs.jsx (Add Chart Imports and Rendering)

In `PROD/frontend/src/pages/Logs.jsx`:

**Add imports at the top** (after the existing imports):
```javascript
import RouteUptimeChart from '../components/RouteUptimeChart';
import RouteUptimePanel from '../components/RouteUptimePanel';
```

**Add below the log output** (after the `{logData && (` block closes its `</div>`):
```jsx
{/* Route Uptime Panel — time-range based (traffic report API) */}
<RouteUptimePanel
  routes={logFiles}
  selectedRouteId={logFiles.find((f) => f.file === selectedFile)?.route_id || ''}
/>

{/* Route Uptime Chart — from fetched log lines (quick view) */}
{logData && logData.lines.length > 0 && (
  <RouteUptimeChart logLines={logData.lines} fileName={logData.file} />
)}
```

### Step 2.3 — Update Notifications.jsx (Add CLIENT_ERROR)

In `PROD/frontend/src/pages/Notifications.jsx`:

**Add to CONDITION_LABELS** (after the `POD_HEALTH` entry):
```javascript
  CLIENT_ERROR: 'Client Error (4xx)',
```

**Add to CONDITION_TYPES** (after the `POD_HEALTH` entry):
```javascript
  { value: 'CLIENT_ERROR', label: 'Client Error (4xx)' },
```

### Step 2.4 — Build and Deploy Frontend

```bash
cd PROD/frontend
npx vite build

# Use tar to exclude node_modules (too large for --from-dir):
tar -czf ../build.tar.gz --exclude="node_modules" --exclude=".git" --exclude="src" -C . .
oc start-build apisix-dashboard-frontend --from-archive=../build.tar.gz --follow -n cro-apisix-prod
oc rollout restart deployment/apisix-dashboard-frontend -n cro-apisix-prod
rm ../build.tar.gz
```

### Step 2.5 — Verify Frontend

1. Open PROD dashboard: `https://cro-apisix-croit-dashboard-prod.apps.prod-01-rb.ocp.fnb.co.za`
2. Go to **Notifications** → Create Rule → verify "Client Error (4xx)" appears in condition type dropdown
3. Go to **Log Viewer** → select a route → fetch logs → verify the Uptime Panel and Chart appear below the log output
4. Check the Route Uptime Panel presets (Today, Yesterday, 1h, 3h, 6h) return data correctly

---

## Part 3: Post-Deployment Verification

### Alert System Checks

| Check | How | Expected |
|-------|-----|----------|
| Parser working | Check logs for `found_in_metrics=True` | All metric rules find their routes |
| Evaluation at 10s | Check backend logs | `"Notification scheduler started (interval=10s)."` |
| CLIENT_ERROR detection | Wait for a 4xx error | Alert email within 10 seconds |
| No false positives | Monitor for 30 min after initial startup alert | No repeat emails while route returns 200s |
| Recovery email | After alert fires and route recovers | Single recovery email sent |
| Pod recreation alert | Next pod restart | Email with "Pod recreated" reason |

### Expected First-Startup Behaviour

After deploying, the backend will fire ONE alert for each CLIENT_ERROR rule on startup (HWM goes from 0 to current cumulative count). This is expected. After that initial email, the HWM is set and no further alerts fire unless genuinely new errors occur.

### Log Viewer Chart Checks

| Check | How | Expected |
|-------|-----|----------|
| RouteUptimePanel renders | Select a route in Log Viewer | Panel shows with time presets (Today, Yesterday, 1h-12h) |
| RouteUptimeChart renders | Fetch logs for a route | Response time chart with red error dots appears |
| Cross-midnight presets work | At e.g. 2 AM, select "6h" preset | Shows data from both yesterday and today merged |
| Error Events table | When 4xx/5xx exist in logs | Table shows each error with Time, Status, Method, URI, Latency |

---

## Rollback

### Backend Rollback
If the backend has issues:
```bash
# Revert to previous image (OpenShift keeps previous ReplicaSets)
oc rollout undo deployment/apisix-dashboard-backend -n cro-apisix-prod
```

### Frontend Rollback
If the frontend has issues:
```bash
oc rollout undo deployment/apisix-dashboard-frontend -n cro-apisix-prod
```

### ConfigMap Rollback (if 10s interval causes issues)
```bash
oc patch configmap apisix-dashboard-config -n cro-apisix-prod \
  --type=merge -p '{"data":{"NOTIFICATION_EVAL_INTERVAL":"60"}}'
oc rollout restart deployment/apisix-dashboard-backend -n cro-apisix-prod
```

---

## Files Summary

### Files to COPY from UAT to PROD

| Source (UAT) | Destination (PROD) | Reason |
|-------------|-------------------|--------|
| `backend/app/services/metrics_evaluator.py` | `backend/app/services/metrics_evaluator.py` | Parser fix (spaces in route names) |
| `backend/app/services/background_scheduler.py` | `backend/app/services/background_scheduler.py` | HWM fix + CLIENT_ERROR key + pod recreation + debug logging |
| `backend/app/services/traffic_report_service.py` | `backend/app/services/traffic_report_service.py` | SAST timezone + dynamic tail depth |
| `frontend/src/components/RouteUptimeChart.jsx` | `frontend/src/components/RouteUptimeChart.jsx` | New component |
| `frontend/src/components/RouteUptimePanel.jsx` | `frontend/src/components/RouteUptimePanel.jsx` | New component |

### Files to EDIT in PROD

| File | Change |
|------|--------|
| `frontend/src/pages/Logs.jsx` | Add RouteUptimeChart + RouteUptimePanel imports and rendering |
| `frontend/src/pages/Notifications.jsx` | Add `CLIENT_ERROR` to CONDITION_LABELS and CONDITION_TYPES |

### ConfigMap to UPDATE

| Setting | Current | Target | Reason |
|---------|---------|--------|--------|
| `NOTIFICATION_EVAL_INTERVAL` | 60 | 10 | Real-time screening needs fast detection |

---

## Known Behaviour After Deployment

| Behaviour | Normal? | Why |
|-----------|---------|-----|
| One alert email per CLIENT_ERROR rule on first startup | ✅ Yes | HWM initializes from 0, so first cycle sees all existing errors as "new" |
| Recovery email shortly after the startup alert | ✅ Yes | Next cycle sees delta=0 with 2xx traffic flowing |
| No further alerts until genuinely new 4xx errors | ✅ Yes | HWM locks at the maximum seen count |
| APISIX pod restart resets Prometheus counters | ⚠️ Watch | If counters reset to 0, HWM is still high — no false alert. New errors on the fresh pod won't trigger until they exceed the old HWM. Workaround: restart the dashboard backend to reset the HWM. |

---

## Pre-Deployment Checklist

- [ ] UAT has been running these features successfully for 24+ hours
- [ ] CLIENT_ERROR alerts fire only on genuinely new errors (no false positives from pod switching)
- [ ] Recovery emails send correctly when errors stop
- [ ] Route Uptime Panel presets work correctly on UAT
- [ ] Prometheus parser logs show `found_in_metrics=True` for all configured routes
- [ ] Logged into PROD cluster with valid token
- [ ] Backend tests pass locally before deployment
- [ ] Frontend builds without errors (`npx vite build`)
- [ ] Team aware of expected one-time startup alert email
