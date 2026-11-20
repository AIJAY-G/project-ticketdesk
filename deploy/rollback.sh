#!/usr/bin/env bash
# ==============================================================================
# TicketDesk Application Rollback Script (Amazon Linux 2023)
# ==============================================================================
# Restores application directory from the latest backup snapshot.
# Usage:
#   sudo bash deploy/rollback.sh
# ==============================================================================

set -euo pipefail

INSTALL_DIR="/opt/ticketdesk"

echo "======================================================================"
echo "Starting TicketDesk Rollback"
echo "======================================================================"

if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: This script must be executed as root or via sudo." >&2
    exit 1
fi

# Locate the most recent backup directory
LATEST_BACKUP=$(ls -td ${INSTALL_DIR}.bak.* 2>/dev/null | head -n 1 || true)

if [[ -z "${LATEST_BACKUP}" ]] || [[ ! -d "${LATEST_BACKUP}" ]]; then
    echo "ERROR: No backup directory found matching '${INSTALL_DIR}.bak.*'." >&2
    exit 1
fi

echo "Found latest backup: ${LATEST_BACKUP}"

# Stop the application service during rollback
echo "Stopping ticketdesk.service..."
systemctl stop ticketdesk.service

# Preserve current .env if it exists
TMP_ENV=$(mktemp)
if [[ -f "${INSTALL_DIR}/app/.env" ]]; then
    cp "${INSTALL_DIR}/app/.env" "${TMP_ENV}"
fi

# Restore files from backup
echo "Restoring application files from ${LATEST_BACKUP}..."
rm -rf "${INSTALL_DIR}"
cp -r "${LATEST_BACKUP}" "${INSTALL_DIR}"

# Restore preserved .env
if [[ -s "${TMP_ENV}" ]]; then
    cp "${TMP_ENV}" "${INSTALL_DIR}/app/.env"
    chmod 600 "${INSTALL_DIR}/app/.env"
    chown ticketdesk:ticketdesk "${INSTALL_DIR}/app/.env"
fi
rm -f "${TMP_ENV}"

# Fix ownership
chown -R ticketdesk:ticketdesk "${INSTALL_DIR}"

# Restart services
echo "Restarting services..."
systemctl restart ticketdesk.service
systemctl restart nginx

echo "======================================================================"
echo "Rollback Complete!"
echo "Service Status: $(systemctl is-active ticketdesk.service)"
echo "Nginx Status:   $(systemctl is-active nginx.service)"
echo "======================================================================"
