#!/usr/bin/env bash
# ==============================================================================
# TicketDesk Application EC2 Deployment Script (Amazon Linux 2023)
# ==============================================================================
# Sets up Python 3.11 virtual environment, systemd service, and Nginx reverse proxy.
# Usage:
#   sudo bash deploy/install.sh
# ==============================================================================

set -euo pipefail

# Configuration Constants
APP_USER="ticketdesk"
APP_GROUP="ticketdesk"
INSTALL_DIR="/opt/ticketdesk"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_NAME="ticketdesk"

echo "======================================================================"
echo "Starting TicketDesk EC2 Installation & Service Setup"
echo "Target Directory: ${INSTALL_DIR}"
echo "======================================================================"

# 1. Root / Sudo Privilege Check
if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: This script must be executed as root or via sudo." >&2
    exit 1
fi

# 2. Determine Script Location & Project Source
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 3. Install Required OS Packages (Amazon Linux 2023)
echo "[1/8] Installing OS dependencies (Python 3.11, pip, git, nginx)..."
dnf update -y -q
dnf install -y -q python3.11 python3.11-pip git nginx

# 4. Create Dedicated Non-Root System User & Group
if ! id "${APP_USER}" &>/dev/null; then
    echo "[2/8] Creating system user '${APP_USER}'..."
    useradd --system --no-create-home --shell /sbin/nologin "${APP_USER}"
else
    echo "[2/8] System user '${APP_USER}' already exists."
fi

# 5. Create Directory Hierarchy
echo "[3/8] Preparing application directory structure at ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}/app"
mkdir -p "${INSTALL_DIR}/app/uploads"
mkdir -p "${INSTALL_DIR}/deploy"

# 6. Copy Application Code
echo "[4/8] Deploying application codebase..."
# Backup existing version if present
if [[ -d "${INSTALL_DIR}/app" ]] && [[ -f "${INSTALL_DIR}/app/main.py" ]]; then
    cp -r "${INSTALL_DIR}" "${INSTALL_DIR}.bak.$(date +%Y%m%d%H%M%S)" || true
fi

cp -r "${PROJECT_ROOT}/app/"* "${INSTALL_DIR}/app/"
cp -r "${PROJECT_ROOT}/deploy/"* "${INSTALL_DIR}/deploy/"

# 7. Setup Python 3.11 Virtual Environment
echo "[5/8] Configuring Python 3.11 virtual environment..."
if [[ ! -d "${VENV_DIR}" ]]; then
    python3.11 -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/pip" install --upgrade pip -q
"${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/app/requirements.txt" -q

# 8. Setup Environment Configuration File
if [[ ! -f "${INSTALL_DIR}/app/.env" ]]; then
    echo "[6/8] Creating placeholder .env from production template..."
    cp "${INSTALL_DIR}/deploy/.env.production.template" "${INSTALL_DIR}/app/.env"
    chmod 600 "${INSTALL_DIR}/app/.env"
    chown "${APP_USER}:${APP_GROUP}" "${INSTALL_DIR}/app/.env"
    echo "WARNING: /opt/ticketdesk/app/.env created with placeholder values."
    echo "You must edit this file with real RDS and S3 parameters before the app can connect to PostgreSQL!"
else
    echo "[6/8] Existing .env file retained at ${INSTALL_DIR}/app/.env."
fi

# Fix Ownership & Permissions
chown -R "${APP_USER}:${APP_GROUP}" "${INSTALL_DIR}"
chmod 750 "${INSTALL_DIR}"
chmod 750 "${INSTALL_DIR}/app/uploads"

# 9. Configure systemd Service
echo "[7/8] Installing systemd service..."
cp "${INSTALL_DIR}/deploy/ticketdesk.service" /etc/systemd/system/ticketdesk.service
systemctl daemon-reload
systemctl enable ticketdesk.service

# 10. Configure Nginx Reverse Proxy
echo "[8/8] Configuring Nginx reverse proxy..."
# Remove default AL2023 server configuration if present to avoid port 80 collisions
if [[ -f /etc/nginx/conf.d/default.conf ]]; then
    mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.disabled || true
fi

cp "${INSTALL_DIR}/deploy/nginx-ticketdesk.conf" /etc/nginx/conf.d/ticketdesk.conf

# Test Nginx Configuration Syntax
nginx -t

systemctl enable nginx
systemctl restart nginx

# Start or Restart TicketDesk Application
systemctl restart ticketdesk.service

echo "======================================================================"
echo "TicketDesk Installation Complete!"
echo "Service Status: $(systemctl is-active ticketdesk.service)"
echo "Nginx Status:   $(systemctl is-active nginx.service)"
echo "======================================================================"
echo "NEXT STEPS:"
echo "1. Edit /opt/ticketdesk/app/.env with real RDS address and S3 bucket:"
echo "     sudo nano /opt/ticketdesk/app/.env"
echo "2. Restart application:"
echo "     sudo systemctl restart ticketdesk"
echo "3. Inspect logs:"
echo "     sudo journalctl -u ticketdesk -f"
echo "======================================================================"
