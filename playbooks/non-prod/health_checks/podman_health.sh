#!/bin/bash
set -e
set -o pipefail

ANSIBLE_BIN="/usr/bin/ansible-playbook"
PLAY_DIR="/opt/podman/CROIT/playbooks/health_checks"
PLAYBOOK="$PLAY_DIR/pod-health.yml"
LOG_FILE="/opt/podman/CROIT/playbooks/health_checks/podman_health.log"

echo "===== $(date '+%F %T') START =====" >> "$LOG_FILE"

cd "$PLAY_DIR"

# Run against localhost with local connection (no SSH, no other user)
"$ANSIBLE_BIN" \
  -i localhost, \
  -c local \
  -e notify_enabled=true \
  "$PLAYBOOK" >> "$LOG_FILE" 2>&1

echo "===== $(date '+%F %T') END =====" >> "$LOG_FILE"