# ControlM Trigger File Puller — Setup Guide

## Overview

This guide covers deploying the pull-based ControlM trigger file delivery system on the Linux server (`frm-rbautodev01`). The script polls the APISIX Dashboard API every 60 seconds and writes trigger files to a local directory where ControlM's File Watcher picks them up.

## Architecture

```
OpenShift (UAT)                         Linux Server (frm-rbautodev01)
┌─────────────────────┐                 ┌──────────────────────────────────┐
│ APISIX Dashboard    │                 │                                  │
│ Backend Pod         │   ← HTTPS ←    │  controlm_pull_triggers.sh       │
│                     │                 │  (cron: every 60 seconds)        │
│ /app/data/          │                 │          │                       │
│   controlm_alerts/  │                 │          ▼                       │
│   ├── CROIT_ALERT_*.trigger           │  /opt/podman/controlm-puller/    │
│   └── .picked_up/   │                 │    landing_zone/                 │
│       └── (archived)│                 │    ├── CROIT_ALERT_*.trigger ←── ControlM
│                     │                 │    └── .processed/ (optional)    │  File Watcher
└─────────────────────┘                 └──────────────────────────────────┘
```

## Prerequisites

- Access to `frm-rbautodev01` as the `podman` user
- `curl` installed (standard on RHEL)
- The Linux server can reach the UAT dashboard route (verified: HTTPS works)
- A shared API key configured on both ends

## Step 1: Generate a Secure API Key

On your Windows machine (or anywhere):

```powershell
# Generate a random 32-character key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Example output: `dG9rZW4tZXhhbXBsZS1rZXktMTIzNDU2Nzg5MA`

Save this key — you'll need it in both Step 2 and Step 3.

## Step 2: Configure the Dashboard Backend (OpenShift)

Add the API key to the UAT backend's environment. Either:

**Option A: ConfigMap (recommended)**
```bash
oc set env deployment/apisix-dashboard-backend \
  CONTROLM_PULL_API_KEY="<your-generated-key>" \
  -n cro-apisix-uat
```

**Option B: .env file (if using local file)**
Add to `UAT/backend/.env`:
```
CONTROLM_PULL_API_KEY=<your-generated-key>
```

Then redeploy the backend:
```bash
oc rollout restart deployment/apisix-dashboard-backend -n cro-apisix-uat
```

## Step 3: Deploy the Pull Script on the Linux Server

### 3.1 Create the directory structure

```bash
# As the podman user on frm-rbautodev01
mkdir -p /opt/podman/controlm-puller/landing_zone
mkdir -p /opt/podman/controlm-puller/logs
```

### 3.2 Copy the script

From your Windows machine:
```powershell
scp UAT\backend\scripts\controlm_pull_triggers.sh f5151422@frm-rbautodev01:/tmp/
```

On the Linux server:
```bash
# As podman user
cp /tmp/controlm_pull_triggers.sh /opt/podman/controlm-puller/
chmod +x /opt/podman/controlm-puller/controlm_pull_triggers.sh
```

### 3.3 Configure the script

Edit the configuration section at the top of the script:

```bash
vi /opt/podman/controlm-puller/controlm_pull_triggers.sh
```

Update these values:
```bash
# Dashboard API base URL (UAT)
DASHBOARD_URL="https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb.ocp.fnb.co.za"

# Shared API key (must match CONTROLM_PULL_API_KEY in the dashboard .env)
API_KEY="<your-generated-key-from-step-1>"

# Local landing zone where ControlM File Watcher will pick up the files
LANDING_ZONE="/opt/podman/controlm-puller/landing_zone"

# Log file
LOG_FILE="/opt/podman/controlm-puller/logs/puller.log"
```

### 3.4 Test manually

```bash
# Run the script once to verify connectivity
/opt/podman/controlm-puller/controlm_pull_triggers.sh

# Check the log
cat /opt/podman/controlm-puller/logs/puller.log
```

Expected output (when no alerts are active):
```
[2026-06-18 14:30:00] --- Pull cycle started ---
[2026-06-18 14:30:01] No pending trigger files.
```

## Step 4: Set Up the Cron Job

```bash
# Edit crontab for the podman user
crontab -e
```

Add this line:
```cron
* * * * * /opt/podman/controlm-puller/controlm_pull_triggers.sh
```

This runs the script every 60 seconds. Combined with ControlM's 1-minute File Watcher interval, worst-case detection time is ~2 minutes from alert trigger to phone call.

### Verify cron is running

```bash
# Check crontab was saved
crontab -l

# After 1-2 minutes, check the log
tail -20 /opt/podman/controlm-puller/logs/puller.log
```

## Step 5: Configure ControlM File Watcher

Provide the ControlM team with this specification:

| Parameter | Value |
|-----------|-------|
| FOLDER_NAME | `CROITESCALATION` |
| JOBNAME | `CROIT_DASHBOARD_ALERT_FW` |
| FILE_PATH | `/opt/podman/controlm-puller/landing_zone/` |
| FILE_NAME | `CROIT_ALERT_*.trigger` |
| SEARCH_INTERVAL | 1 minute |
| MIN_FILE_AGE | 5 seconds |
| ON_FOUND | Trigger phone-call escalation to 1st call / standby |
| BU_NAME | CRO IT Application Support |

## Testing End-to-End

### Create a test trigger manually

On the OpenShift pod (or via local dev):
```bash
# Write a test file to the landing zone inside the pod
oc exec deployment/apisix-dashboard-backend -n cro-apisix-uat -- \
  sh -c 'mkdir -p /app/data/controlm_alerts && echo "rule_name=TEST_RULE
route_id=12345
route_name=Test Route
condition_type=UPSTREAM_ERROR
failure_message=Manual test trigger
alert_timestamp=2026-06-18T14:00:00Z
severity=WARNING" > /app/data/controlm_alerts/CROIT_ALERT_TEST_RULE_20260618_140000.trigger'
```

### Verify the pull

Wait 60 seconds (or run the script manually on the Linux server):
```bash
/opt/podman/controlm-puller/controlm_pull_triggers.sh
```

Check the results:
```bash
# File should appear in the landing zone
ls -la /opt/podman/controlm-puller/landing_zone/

# Log should show the download
tail -10 /opt/podman/controlm-puller/logs/puller.log
```

### Clean up test file
```bash
rm -f /opt/podman/controlm-puller/landing_zone/CROIT_ALERT_TEST_RULE_20260618_140000.trigger
```

## Log Rotation

Add a logrotate config to prevent unbounded log growth:

```bash
cat > /opt/podman/controlm-puller/logrotate.conf << 'EOF'
/opt/podman/controlm-puller/logs/puller.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
EOF
```

Add to crontab (daily at midnight):
```cron
0 0 * * * /usr/sbin/logrotate /opt/podman/controlm-puller/logrotate.conf --state /opt/podman/controlm-puller/logrotate.state
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Failed to connect to dashboard API" | Network/DNS issue | Run `curl -sk --noproxy '*' https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb.ocp.fnb.co.za/health` |
| "API returned error: ...503..." | `CONTROLM_PULL_API_KEY` not set in dashboard | Set the env var and restart backend deployment |
| "API returned error: ...401..." | API key mismatch | Verify the key matches between script and dashboard config |
| Files appear but ControlM doesn't fire | File Watcher not configured | Confirm with ControlM team that the job is active |
| "No pending trigger files" constantly | No alerts are triggering | Create a test file (see Testing section) |
| Log file growing too large | Log rotation not set up | Add the logrotate config above |

## Security Notes

- The API key is a shared secret — treat it like a password
- The script uses `--noproxy '*'` to bypass the corporate proxy (internal traffic only)
- The script uses `-k` (insecure) because of corporate self-signed certificates on the route
- Files are written atomically (temp + mv) to prevent ControlM from reading partial files
- The download endpoint validates filenames against a strict regex to prevent path traversal
