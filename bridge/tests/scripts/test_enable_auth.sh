#!/bin/bash
# Test enable_auth_for_device.sh against the real config.yaml
# (with snapshot/rollback for safety)
set -e
SCRIPT="/root/projects/xiaozhi-bridge/scripts/enable_auth_for_device.sh"
REPO_CONFIG="/root/projects/xiaozhi-bridge/config/config.yaml"
TMPDIR=$(mktemp -d)
cp "$REPO_CONFIG" "$TMPDIR/config.yaml.bak"
trap "cp $TMPDIR/config.yaml.bak $REPO_CONFIG; rm -rf $TMPDIR; rm -f ${REPO_CONFIG}.bak.*" EXIT

# --- Test 1: add first device ---
echo "=== Test 1: add first device esp32-001 ==="
bash "$SCRIPT" esp32-001 tok-aaa
grep -q 'auth_tokens:' "$REPO_CONFIG" || { echo "FAIL: no auth_tokens key"; exit 1; }
grep -q 'esp32-001: "tok-aaa"' "$REPO_CONFIG" || { echo "FAIL: entry not added"; exit 1; }
echo "  PASS"

# --- Test 2: add second device ---
echo "=== Test 2: add second device esp32-002 ==="
bash "$SCRIPT" esp32-002 tok-bbb
grep -q 'esp32-001: "tok-aaa"' "$REPO_CONFIG" || { echo "FAIL: esp32-001 lost"; exit 1; }
grep -q 'esp32-002: "tok-bbb"' "$REPO_CONFIG" || { echo "FAIL: esp32-002 not added"; exit 1; }
echo "  PASS"

# --- Test 3: rotate ---
echo "=== Test 3: rotate esp32-001 token ==="
bash "$SCRIPT" esp32-001 tok-aaa-rotated
grep -q 'esp32-001: "tok-aaa-rotated"' "$REPO_CONFIG" || { echo "FAIL: rotation didn't take"; exit 1; }
grep -q 'esp32-002: "tok-bbb"' "$REPO_CONFIG" || { echo "FAIL: esp32-002 lost"; exit 1; }
echo "  PASS"

# --- Test 4: bad device_id ---
echo "=== Test 4: reject bad device_id ==="
if bash "$SCRIPT" 'bad device id' tok-xxx 2>/dev/null; then
  echo "FAIL: bad device_id was accepted"; exit 1
fi
echo "  PASS (rejected)"

# --- Test 5: bad token ---
echo "=== Test 5: reject bad token ==="
if bash "$SCRIPT" esp32-003 'bad token with spaces' 2>/dev/null; then
  echo "FAIL: bad token was accepted"; exit 1
fi
echo "  PASS (rejected)"

# --- Test 6: missing arg ---
echo "=== Test 6: missing arg ==="
if bash "$SCRIPT" 2>/dev/null; then
  echo "FAIL: missing arg accepted"; exit 1
fi
echo "  PASS (rejected)"

echo
echo "ALL 6 TESTS PASSED"
