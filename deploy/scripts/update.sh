#!/usr/bin/env bash
# xiaozhi-bridge update script
#
# Pulls latest code, reinstalls deps, restarts services.

set -euo pipefail

REPO_DIR="${XIAOZHI_REPO_DIR:-/root/projects/xiaozhi-bridge}"

echo "==> Updating xiaozhi-bridge in ${REPO_DIR}"

cd "${REPO_DIR}"

# Pull latest
if [ -d .git ]; then
    git pull
else
    echo "Not a git repo — skipping pull. Re-run install.sh to bootstrap."
    exit 1
fi

# Python deps
echo "==> Updating Python deps"
cd "${REPO_DIR}/bridge"
uv sync

# Web build
echo "==> Rebuilding web UI"
cd "${REPO_DIR}/web"
if command -v pnpm &>/dev/null; then
    pnpm install
    pnpm build
else
    npm install
    npm run build
fi

# Restart services
echo "==> Restarting services"
sudo systemctl restart xiaozhi-bridge.service xiaozhi-web.service

echo ""
echo "✅ Update complete!"
echo "  sudo journalctl -u xiaozhi-bridge -f    # follow logs"
