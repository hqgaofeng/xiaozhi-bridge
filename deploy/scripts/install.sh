#!/usr/bin/env bash
# xiaozhi-bridge installation script
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/hqgaofeng/xiaozhi-bridge/main/deploy/scripts/install.sh | bash
#   # or
#   ./deploy/scripts/install.sh

set -euo pipefail

REPO_DIR="${XIAOZHI_REPO_DIR:-/root/projects/xiaozhi-bridge}"
SERVICE_USER="${SERVICE_USER:-root}"

echo "==> Installing xiaozhi-bridge to ${REPO_DIR}"

# --- 1. System dependencies ---
echo "==> Installing system dependencies"
if command -v apt-get &>/dev/null; then
    sudo apt-get update
    sudo apt-get install -y \
        python3.12 python3.12-venv python3-pip \
        nodejs npm \
        libopus0 libopus-dev \
        ffmpeg \
        build-essential
elif command -v dnf &>/dev/null; then
    sudo dnf install -y python3.12 nodejs opus-devel ffmpeg
fi

# --- 2. uv (Python package manager) ---
if ! command -v uv &>/dev/null; then
    echo "==> Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

# --- 3. Python venv ---
echo "==> Setting up Python virtualenv"
cd "${REPO_DIR}/bridge"
# Note: pyproject.toml uses hatchling backend, so we need `uv venv` +
# `uv pip install`, not `uv sync` (which only works with uv-native projects).
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"

# --- 4. Web UI ---
echo "==> Building web admin UI"
cd "${REPO_DIR}/web"
if command -v pnpm &>/dev/null; then
    pnpm install
    pnpm build
else
    npm install
    npm run build
fi

# --- 5. Config ---
if [ ! -f "${REPO_DIR}/config/config.yaml" ]; then
    echo "==> Creating config from template"
    cp "${REPO_DIR}/config/config.example.yaml" "${REPO_DIR}/config/config.yaml"
    echo "    Edit ${REPO_DIR}/config/config.yaml before starting the service."
fi

# --- 6. Log directory ---
sudo mkdir -p /var/log/xiaozhi-bridge
sudo chown ${SERVICE_USER}:${SERVICE_USER} /var/log/xiaozhi-bridge

# --- 7. systemd ---
echo "==> Installing systemd units"
sudo cp "${REPO_DIR}/deploy/systemd/xiaozhi-bridge.service" /etc/systemd/system/
sudo cp "${REPO_DIR}/deploy/systemd/xiaozhi-web.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xiaozhi-bridge.service xiaozhi-web.service

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Edit config:    nano ${REPO_DIR}/config/config.yaml"
echo "  2. Check status:   sudo systemctl status xiaozhi-bridge"
echo "  3. View logs:      sudo journalctl -u xiaozhi-bridge -f"
echo "  4. Web UI:         http://YOUR_VPS_IP:3000"
echo "  5. WebSocket URL:  ws://YOUR_VPS_IP:8000/xiaozhi/v1/"
