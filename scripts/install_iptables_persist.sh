#!/bin/bash
# install_iptables_persist.sh
#
# V2 #2.2 (v0.2.5) — install the iptables-restore systemd service
# so the V2 #2.1 egress-fix survives host reboots.
#
# Usage (as root, after V2 #2.1's manual iptables edits):
#   sudo ./scripts/install_iptables_persist.sh
#
# What it does:
#   1. Save current iptables state to /etc/iptables.rules
#   2. Install the systemd unit to /etc/systemd/system/
#   3. daemon-reload + enable + start
#   4. Sanity-check: list the active FORWARD rules
#
# Rollback:
#   sudo systemctl disable --now iptables-restore
#   sudo rm /etc/systemd/system/iptables-restore.service
#   sudo rm /etc/iptables.rules
#   sudo systemctl daemon-reload
#
# Why not iptables-persistent (the apt package)?
#   - It requires interactive debconf prompts during install
#     (asks about saving IPv4/IPv6 rules on every shutdown).
#   - Touches host apt state without Allen's explicit OK.
#   - The systemd unit approach is equally reliable and fully
#     auditable in this repo.

set -euo pipefail

# --- Sanity: must be root ---
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: must run as root (sudo $0)" >&2
    exit 1
fi

# --- Sanity: iptables-restore binary present ---
if ! command -v iptables-restore >/dev/null 2>&1; then
    echo "ERROR: iptables-restore not found in \$PATH" >&2
    exit 1
fi

# --- Sanity: V2 #2.1 fixes already in place (otherwise we'd be
#     persisting an empty/broken state). Look for the bridge iface
#     ACCEPT rule in the current FORWARD chain. ---
if ! iptables -L FORWARD -n -v | grep -q "ACCEPT.*br-de22cc47a0c1"; then
    cat >&2 <<EOF
WARNING: V2 #2.1 FORWARD ACCEPT rule for br-de22cc47a0c1 not
detected in the current FORWARD chain. This usually means the
manual iptables fix from V2 #2.1 has not been applied yet.

If you have already applied V2 #2.1 but the bridge iface name
changed (recreated docker network), grep the right name and
adjust the unit file before running this script.

Proceeding anyway — iptables-save will capture whatever is in
the current state (possibly missing the V2 #2.1 rules).
EOF
    read -r -p "Continue? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

# --- Step 1: Save current iptables state ---
echo "==> Saving current iptables state to /etc/iptables.rules"
# iptables-save emits comments with packet counters; we strip
# the timestamp so the file is deterministic across reboots
# (avoids spurious "config changed" logs in journald).
iptables-save | sed -E 's/ on [A-Z][a-z]{2} [A-Z][a-z]{2} +[0-9]+ +[0-9:]+ +[0-9]{4}$//' \
    > /etc/iptables.rules
chmod 644 /etc/iptables.rules
echo "    saved: $(wc -l < /etc/iptables.rules) lines, $(stat -c %s /etc/iptables.rules) bytes"

# --- Step 2: Install the systemd unit ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="$SCRIPT_DIR/../deploy/iptables-restore.service"
UNIT_DST="/etc/systemd/system/iptables-restore.service"

if [[ ! -f "$UNIT_SRC" ]]; then
    echo "ERROR: unit file not found at $UNIT_SRC" >&2
    echo "  (expected: deploy/iptables-restore.service in this repo)" >&2
    exit 1
fi

echo "==> Installing systemd unit to $UNIT_DST"
install -m 644 "$UNIT_SRC" "$UNIT_DST"

# --- Step 3: daemon-reload + enable + start ---
echo "==> Reloading systemd, enabling and starting service"
systemctl daemon-reload
systemctl enable iptables-restore.service
systemctl start iptables-restore.service

# --- Step 4: Sanity-check ---
sleep 1
echo
echo "==> Active FORWARD rules (top 5):"
iptables -L FORWARD -n -v --line-numbers | head -7
echo
echo "==> Active NAT POSTROUTING rules (top 5):"
iptables -t nat -L POSTROUTING -n -v --line-numbers | head -5
echo
echo "==> Service status:"
systemctl is-active iptables-restore.service && echo "  ACTIVE"
echo
echo "DONE. iptables rules will now survive host reboots."
echo "To verify after a real reboot, run:"
echo "  sudo iptables -L FORWARD -n | grep br-de22cc47a0c1"
