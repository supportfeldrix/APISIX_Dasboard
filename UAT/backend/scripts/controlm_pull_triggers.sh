#!/bin/bash
# ===========================================================================
# ControlM Trigger File Pull Script
# ===========================================================================
#
# Purpose:
#   Pulls pending trigger files from the APISIX Dashboard backend API and
#   writes them to the local landing zone where ControlM File Watcher picks
#   them up for phone-call escalation.
#
# How it works:
#   1. Calls GET /api/escalation/pending-triggers to list available files
#   2. For each file, calls GET /api/escalation/download-trigger/{filename}
#   3. Writes the file atomically to the local landing zone (temp + mv)
#   4. Calls POST /api/escalation/acknowledge-pickup/{filename} to confirm
#   5. Logs all activity to a local log file
#
# Authentication:
#   Uses a shared API key passed in the X-ControlM-Key header.
#   Configure this key in the dashboard's .env as CONTROLM_PULL_API_KEY
#   and in this script's config below.
#
# Deployment:
#   - Copy to /opt/podman/controlm-puller/ on frm-rbautodev01
#   - chmod +x controlm_pull_triggers.sh
#   - Configure the variables below
#   - Add to crontab: * * * * * /opt/podman/controlm-puller/controlm_pull_triggers.sh
#
# ===========================================================================

# ---------------------------------------------------------------------------
# Configuration — EDIT THESE FOR YOUR ENVIRONMENT
# ---------------------------------------------------------------------------

# Dashboard API base URL (UAT)
DASHBOARD_URL="https://cro-apisix-croit-dashboard-uat.apps.dev-02-rb.ocp.fnb.co.za"

# Shared API key (must match CONTROLM_PULL_API_KEY in the dashboard .env)
API_KEY="CHANGE_ME_TO_A_SECURE_KEY"

# Local landing zone where ControlM File Watcher will pick up the files
LANDING_ZONE="/opt/podman/controlm-puller/landing_zone"

# Log file
LOG_FILE="/opt/podman/controlm-puller/logs/puller.log"

# Curl options (corporate self-signed certs — skip verification)
CURL_OPTS="--silent --show-error --max-time 30 --noproxy '*' -k"

# ---------------------------------------------------------------------------
# DO NOT EDIT BELOW THIS LINE
# ---------------------------------------------------------------------------

# Ensure directories exist
mkdir -p "$LANDING_ZONE"
mkdir -p "$(dirname "$LOG_FILE")"

# Logging helper
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "--- Pull cycle started ---"

# ---------------------------------------------------------------------------
# Step 1: List pending trigger files
# ---------------------------------------------------------------------------

RESPONSE=$(curl $CURL_OPTS \
    -H "X-ControlM-Key: $API_KEY" \
    -H "Accept: application/json" \
    "${DASHBOARD_URL}/api/escalation/pending-triggers" 2>&1)

CURL_EXIT=$?

if [ $CURL_EXIT -ne 0 ]; then
    log "ERROR: Failed to connect to dashboard API (curl exit: $CURL_EXIT): $RESPONSE"
    exit 1
fi

# Check for HTTP error responses
if echo "$RESPONSE" | grep -q '"detail"'; then
    log "ERROR: API returned error: $RESPONSE"
    exit 1
fi

# Extract filenames using lightweight JSON parsing (no jq dependency)
# Expected format: {"files": [{"filename": "CROIT_ALERT_...", ...}, ...]}
FILENAMES=$(echo "$RESPONSE" | grep -oP '"filename"\s*:\s*"\K[^"]+')

if [ -z "$FILENAMES" ]; then
    log "No pending trigger files."
    exit 0
fi

FILE_COUNT=$(echo "$FILENAMES" | wc -l)
log "Found $FILE_COUNT pending trigger file(s)."

# ---------------------------------------------------------------------------
# Step 2 & 3: Download each file and write to landing zone
# ---------------------------------------------------------------------------

DOWNLOADED=0
FAILED=0

while IFS= read -r FILENAME; do
    log "Downloading: $FILENAME"

    # Download file content
    CONTENT=$(curl $CURL_OPTS \
        -H "X-ControlM-Key: $API_KEY" \
        "${DASHBOARD_URL}/api/escalation/download-trigger/${FILENAME}" 2>&1)

    CURL_EXIT=$?

    if [ $CURL_EXIT -ne 0 ]; then
        log "ERROR: Failed to download $FILENAME (curl exit: $CURL_EXIT)"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Check for error response
    if echo "$CONTENT" | grep -q '"detail"'; then
        log "ERROR: Download error for $FILENAME: $CONTENT"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Atomic write: write to temp file then rename
    TEMP_FILE="${LANDING_ZONE}/.tmp_${FILENAME}"
    FINAL_FILE="${LANDING_ZONE}/${FILENAME}"

    echo "$CONTENT" > "$TEMP_FILE"

    if [ $? -ne 0 ]; then
        log "ERROR: Failed to write temp file for $FILENAME"
        rm -f "$TEMP_FILE"
        FAILED=$((FAILED + 1))
        continue
    fi

    mv "$TEMP_FILE" "$FINAL_FILE"

    if [ $? -ne 0 ]; then
        log "ERROR: Failed to rename temp file to $FINAL_FILE"
        rm -f "$TEMP_FILE"
        FAILED=$((FAILED + 1))
        continue
    fi

    log "Written: $FINAL_FILE"

    # ---------------------------------------------------------------------------
    # Step 4: Acknowledge pickup
    # ---------------------------------------------------------------------------

    ACK_RESPONSE=$(curl $CURL_OPTS \
        -X POST \
        -H "X-ControlM-Key: $API_KEY" \
        -H "Content-Type: application/json" \
        "${DASHBOARD_URL}/api/escalation/acknowledge-pickup/${FILENAME}" 2>&1)

    ACK_EXIT=$?

    if [ $ACK_EXIT -ne 0 ]; then
        log "WARNING: Downloaded $FILENAME but failed to acknowledge (curl exit: $ACK_EXIT)"
        # Don't increment FAILED — the file was still written successfully
    elif echo "$ACK_RESPONSE" | grep -q '"success"'; then
        log "Acknowledged: $FILENAME"
    else
        log "WARNING: Acknowledge response unexpected: $ACK_RESPONSE"
    fi

    DOWNLOADED=$((DOWNLOADED + 1))

done <<< "$FILENAMES"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

log "Pull cycle complete: $DOWNLOADED downloaded, $FAILED failed."

if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0
