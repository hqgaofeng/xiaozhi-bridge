#!/bin/bash
# enable_auth_for_device.sh
#
# V2 #6.2 (v0.2.8) — one-shot helper to add a device_id →
# bearer-token entry to config/config.yaml under
# `device.auth_tokens`.
#
# Usage (on the VPS, after a device has connected at least
# once and shows up in /api/devices):
#
#   sudo ./scripts/enable_auth_for_device.sh <device_id> <token>
#
# Examples:
#
#   # Whitelist the existing esp32-001 with a fresh token,
#   # then patch the firmware to send 'Authorization: Bearer xyz'.
#   sudo ./scripts/enable_auth_for_device.sh esp32-001 tok-living-room-xyz
#
#   # Look up the device_id by listing /api/devices:
#   curl -s http://127.0.0.1:8001/api/devices | python3 -m json.tool
#
# What it does:
#   1. Validates the device_id and token (no spaces, no 'Bearer '
#      prefix — we add that automatically in the firmware).
#   2. Backs up config/config.yaml to a timestamped file
#      (config/config.yaml.bak.YYYYMMDD-HHMMSS) so the change
#      is recoverable.
#   3. Inserts/updates the device's entry under
#      `device.auth_tokens:` (creating the key if missing,
#      updating the value if the device is already listed).
#   4. Prints the diff so you can review what changed.
#   5. Reminds you to restart the bridge container.
#
# Why a shell script (not python)?
#   - The action is a 5-line YAML edit; a python argparse
#     wrapper would be more code than the actual work.
#   - It keeps the operator's mental model simple: 'edit
#     config.yaml, restart bridge'. No new tool to learn.
#   - Easy to inspect and modify in-place.
#
# Rollback (if you fat-fingered the token):
#   sudo cp config/config.yaml.bak.YYYYMMDD-HHMMSS config/config.yaml
#   docker compose restart bridge
#
# Why NOT a python script that talks to the HTTP API?
#   - PATCH /api/devices/{id} is for human-friendly metadata
#     (name/notes/room), not secrets. We don't want tokens
#     in the SQLite DB file because:
#       (a) backups would include plaintext secrets,
#       (b) the bridge would need to read from DB on every
#           handshake (extra round-trip per connect).
#   - Config file is the right place for static secrets
#     that are set up at deploy time, not mutated often.

set -euo pipefail

# --- Sanity: arg count + non-root ok ---
if [[ $# -ne 2 ]]; then
    cat >&2 <<EOF
Usage: $0 <device_id> <token>

  device_id  the ESP32's Device-Id header value (e.g. esp32-001,
             a MAC address, or any string the firmware sets).
  token      the bearer token the firmware will send in
             'Authorization: Bearer <token>'. No 'Bearer '
             prefix, no spaces. Use a unique per-device
             secret; rotate by re-running with a new value.

Finds config.yaml relative to the script's repo root:
  $(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/config/config.yaml
EOF
    exit 1
fi

DEVICE_ID="$1"
TOKEN="$2"

# --- Sanity: shape of the inputs ---
# Reject anything that would break the YAML or look like an
# injection attempt. Tokens with spaces or colons are
# technically valid YAML scalars when quoted, but we want
# to keep this simple — the firmware side also has to
# reconstruct the header byte-for-byte.
if [[ ! "$DEVICE_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "ERROR: device_id must match [A-Za-z0-9._-]+ (got: '$DEVICE_ID')" >&2
    echo "  (if your device_id has other chars, edit config.yaml by hand)" >&2
    exit 1
fi
if [[ ! "$TOKEN" =~ ^[A-Za-z0-9._/+=-]+$ ]]; then
    echo "ERROR: token must match [A-Za-z0-9._/+=-]+ (got: '$TOKEN')" >&2
    echo "  Generate one with: openssl rand -hex 24" >&2
    exit 1
fi

# --- Locate config.yaml (relative to the script's repo root) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="$REPO_ROOT/config/config.yaml"

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: config not found at $CONFIG" >&2
    exit 1
fi

# --- Backup (timestamped, never overwritten) ---
TS=$(date +%Y%m%d-%H%M%S)
BAK="$CONFIG.bak.$TS"
cp "$CONFIG" "$BAK"
echo "==> backed up to $BAK"

# --- Patch ---
# 1. Ensure `auth_tokens:` key exists under `device:`. If
#    `device:` has no `auth_tokens:` yet, we add it after
#    the `auth_token:` line.
# 2. Insert/update the device entry.
#
# We use a small python one-liner for the YAML edit because
# writing a robust sed/awk YAML patcher is its own rabbit
# hole (indentation, comments, existing key presence).
# PyYAML is already in the bridge container image but we
# don't want to depend on it being on the host; instead we
# do a regex-based edit that's good enough for the well-
# known shape of our config.yaml.

if grep -qE '^[[:space:]]+auth_tokens:[[:space:]]*\{?\}' "$CONFIG"; then
    # auth_tokens: {} is present — replace with the open-map
    # form and add the new entry on the next line.
    # (Preserves the comment block above it.)
    python3 - "$CONFIG" "$DEVICE_ID" "$TOKEN" <<'PYEOF'
import sys, re
cfg, dev, tok = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(cfg).read()
# Replace the empty-map form with the open-map form + new entry.
# Match any whitespace before 'auth_tokens' to preserve indent.
new = re.sub(
    r'^(?P<indent>[ \t]+)auth_tokens:[ \t]*\{\}[ \t]*$',
    lambda m: f"{m.group('indent')}auth_tokens:\n{m.group('indent')}  {dev}: \"{tok}\"",
    text,
    count=1,
    flags=re.MULTILINE,
)
if new == text:
    sys.exit("could not find 'auth_tokens: {}' line to replace")
open(cfg, "w").write(new)
PYEOF
elif grep -qE '^[[:space:]]+auth_tokens:' "$CONFIG"; then
    # auth_tokens key exists and is not empty — update or
    # add the entry under it. We append at the end of the
    # map (correct YAML; order is irrelevant for dict lookups).
    python3 - "$CONFIG" "$DEVICE_ID" "$TOKEN" <<'PYEOF'
import sys, re
cfg, dev, tok = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(cfg).read()
# Find the auth_tokens block and add/rewrite the entry.
# Strategy: capture the indented block under auth_tokens:,
# append/update the key.
lines = text.splitlines(keepends=True)
out, in_block, block_indent = [], False, None
key = f'  {dev}:'
for ln in lines:
    stripped = ln.lstrip()
    indent = len(ln) - len(stripped)
    if not in_block:
        if re.match(r'^[ \t]+auth_tokens:[ \t]*$', ln):
            in_block = True
            block_indent = indent
            out.append(ln)
            continue
        out.append(ln)
    else:
        # End of block when we see a non-indented or differently
        # indented line (or EOF).
        if stripped == '' or (indent <= block_indent and not ln.startswith(' ' * (block_indent + 1))):
            in_block = False
            out.append(ln)
            continue
        # Existing entry for this device_id?
        if ln.lstrip().startswith(f'{dev}:') or ln.lstrip().startswith(f'"{dev}":'):
            out.append(f'{" " * (block_indent + 2)}{dev}: "{tok}"\n')
        else:
            out.append(ln)
# Did we ever enter the block? If not, bail.
if not any(re.match(r'^[ \t]+auth_tokens:[ \t]*$', l) for l in out):
    sys.exit("auth_tokens: block not found in output")
# If the device_id entry isn't already in the captured block,
# insert it just after 'auth_tokens:'.
if not any(re.match(rf'^[ \t]+{re.escape(dev)}:', l) for l in out):
    for i, l in enumerate(out):
        if re.match(r'^[ \t]+auth_tokens:[ \t]*$', l):
            out.insert(i + 1, f'{" " * (block_indent + 2)}{dev}: "{tok}"\n')
            break
open(cfg, "w").write("".join(out))
PYEOF
else
    # No auth_tokens key at all — add it after the auth_token
    # line under device:.
    python3 - "$CONFIG" "$DEVICE_ID" "$TOKEN" <<'PYEOF'
import sys, re
cfg, dev, tok = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(cfg).read()
# Insert 'auth_tokens:' + entry on the line after the
# 'auth_token:' line that lives under 'device:'.
m = re.search(
    r'(?P<indent>[ \t]+)auth_token:[ \t]*(?P<v>"[^"]*"|[^\n]*)\n',
    text,
)
if not m:
    sys.exit("could not find device.auth_token: in config; add auth_tokens: by hand")
indent = m.group('indent')
new_block = f'{indent}auth_tokens:\n{indent}  {dev}: "{tok}"\n'
text = text[:m.end()] + new_block + text[m.end():]
open(cfg, "w").write(text)
PYEOF
fi

echo
echo "==> diff ($BAK -> $CONFIG):"
diff "$BAK" "$CONFIG" || true
echo
echo "==> DONE. To apply:"
echo "    cd $REPO_ROOT && docker compose restart bridge"
echo
echo "After the restart, the firmware MUST send 'Authorization: Bearer $TOKEN'"
echo "on every connect, or the bridge will close with reason 'wrong_token'."
echo
echo "To verify the entry took effect:"
echo "    grep -A2 auth_tokens $CONFIG"
