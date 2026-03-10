#!/bin/bash
#
# Podman Health Check Cron Wrapper
#

set -e
set -o pipefail

ANSIBLE_BIN="/usr/bin/ansible-playbook"
ANSIBLE_PLAYBOOK="/opt/podman/CROIT/playbooks/health_checks/pod-health.yml"
INVENTORY_FILE="/opt/podman/CROIT/inventories/local.ini"
LOG_FILE="/opt/podman/CROIT/playbooks/health_checks/podman_health.log"

echo "===== $(date) Starting Podman health check =====" >> "$LOG_FILE"

$ANSIBLE_BIN \
  -i "$INVENTORY_FILE" \
  -e ansible_user=********* \
  -e notify_enabled=true \
  "$ANSIBLE_PLAYBOOK" >> "$LOG_FILE" 2>&1

echo "===== $(date) Finished Podman health check =====" >> "$LOG_FILE"
