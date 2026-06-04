"""Unit tests for V2 #6.1 per-device auth policy.

The policy is a pure function (_check_auth in server.py), so
these tests bypass the WebSocket layer entirely. The WS
handshake just plumbs the headers in and the policy returns
True/False — easy to test the matrix in isolation.
"""

from __future__ import annotations

from xiaozhi_bridge.server import _check_auth

# --- V2 #5 baseline: no auth configured ---


def test_no_policy_allows_everything() -> None:
    """V2 #6.1 contract: empty global + empty map = no auth.

    The V2 #5 default (and the current prod firmware without
    an Authorization header) MUST keep working — adding the
    per-device feature doesn't change the off-by-default
    semantics.
    """
    assert _check_auth(None, None, {}, "") is True
    assert _check_auth("", None, {}, "") is True
    # A real-looking bearer with no policy = still allowed.
    assert (
        _check_auth("Bearer anything", "esp32-001", {}, "") is True
    )


def test_no_policy_allows_missing_device_id() -> None:
    """When no policy is in effect, even unknown device_ids pass.

    This is the V2 #4 'unknown' bucket safety net: firmware
    that forgot the Device-Id header should not be rejected
    by an accidental auth config."""
    assert _check_auth(None, None, {}, "") is True
    assert _check_auth("", "unknown", {}, "") is True


# --- V2 #6.1: global token (legacy single-token config) ---


def test_global_token_required_must_match() -> None:
    """V2 #6.1: when only the global auth_token is set, the
    bearer must equal 'Bearer <global>'. Any other value (or
    missing) is rejected."""
    assert _check_auth("Bearer secret", "esp32-001", {}, "secret") is True
    # Wrong bearer.
    assert _check_auth("Bearer wrong", "esp32-001", {}, "secret") is False
    # Missing header.
    assert _check_auth(None, "esp32-001", {}, "secret") is False
    # Empty header.
    assert _check_auth("", "esp32-001", {}, "secret") is False
    # Wrong scheme.
    assert _check_auth("Basic secret", "esp32-001", {}, "secret") is False


def test_global_token_with_no_device_id() -> None:
    """V2 #6.1: the global token applies even when the device
    didn't send a Device-Id header (V2 #4 'unknown' bucket)."""
    assert _check_auth("Bearer secret", None, {}, "secret") is True
    assert _check_auth("Bearer wrong", None, {}, "secret") is False


# --- V2 #6.1: per-device token (new) ---


def test_per_device_token_match() -> None:
    """V2 #6.1: when a device_id is in the per-device map, the
    bearer must match that device's specific token."""
    tokens = {"esp32-001": "tok-aaa", "esp32-002": "tok-bbb"}
    assert _check_auth("Bearer tok-aaa", "esp32-001", tokens, "") is True
    assert _check_auth("Bearer tok-bbb", "esp32-002", tokens, "") is True
    # Wrong token for the right device.
    assert _check_auth("Bearer tok-aaa", "esp32-002", tokens, "") is False
    assert _check_auth("Bearer tok-bbb", "esp32-001", tokens, "") is False
    # Missing header.
    assert _check_auth(None, "esp32-001", tokens, "") is False


def test_per_device_overrides_global() -> None:
    """V2 #6.1 contract: per-device wins for listed devices,
    even if a global fallback is also set.

    Rationale: an operator with a global token for old firmware
    can add stricter per-device tokens for new devices without
    breaking the old ones. Each device uses its own token
    (no cross-device auth confusion)."""
    tokens = {"esp32-001": "tok-aaa"}
    # Per-device listed: bearer must match per-device.
    assert _check_auth("Bearer tok-aaa", "esp32-001", tokens, "global-fallback") is True
    assert _check_auth("Bearer global-fallback", "esp32-001", tokens, "global-fallback") is False
    # Unlisted device: bearer must match global.
    assert _check_auth("Bearer global-fallback", "esp32-002", tokens, "global-fallback") is True
    assert _check_auth("Bearer tok-aaa", "esp32-002", tokens, "global-fallback") is False


def test_per_device_unlisted_falls_back_to_global() -> None:
    """V2 #6.1: a device not in the per-device map falls back
    to the global token. This is the migration path: roll out
    the per-device map device-by-device, and the rest still
    work with the global token until they're added."""
    tokens = {"esp32-001": "tok-aaa"}
    # Unlisted device with global.
    assert _check_auth("Bearer global", "esp32-999", tokens, "global") is True
    # Unlisted device without global — no policy, allowed.
    assert _check_auth(None, "esp32-999", tokens, "") is True


def test_per_device_with_no_device_id_header() -> None:
    """V2 #6.1: when device_id is missing, the per-device map
    can't apply (no key to look up), so it falls back to the
    global token. If neither is set, no policy = allow."""
    tokens = {"esp32-001": "tok-aaa"}
    # No device_id, no global — no policy, allow.
    assert _check_auth(None, None, tokens, "") is True
    # No device_id, global set — bearer must match global.
    assert _check_auth("Bearer global", None, tokens, "global") is True
    assert _check_auth("Bearer tok-aaa", None, tokens, "global") is False


# --- V2 #6.1: case sensitivity / whitespace ---


def test_bearer_scheme_is_case_sensitive() -> None:
    """V2 #6.1: 'bearer' (lowercase) is NOT accepted — we
    require the canonical 'Bearer' so the comparison is
    unambiguous. This is the same as RFC 6750 §2.1 which
    defines the scheme case-insensitively in principle but
    most server implementations are strict in practice; we
    match the latter for predictability."""
    # Lowercase 'bearer' is rejected.
    assert _check_auth("bearer secret", "esp32-001", {}, "secret") is False
    # 'BEARER' is also rejected.
    assert _check_auth("BEARER secret", "esp32-001", {}, "secret") is False


def test_extra_whitespace_rejected() -> None:
    """V2 #6.1: 'Bearer  secret' (double space) is rejected.

    The comparison is exact-match to keep the test surface
    simple; tokens with whitespace should be regenerated."""
    assert _check_auth("Bearer  secret", "esp32-001", {}, "secret") is False
    assert _check_auth(" Bearer secret", "esp32-001", {}, "secret") is False
    assert _check_auth("Bearer secret ", "esp32-001", {}, "secret") is False


# --- V2 #6.1: empty token in map is treated as no policy ---


def test_empty_string_token_in_map_means_no_policy() -> None:
    """V2 #6.1: an entry like {'esp32-001': ''} in the map
    is treated as 'no policy for this device' (matches the
    default-empty semantics). An operator can use this to
    exempt a single device from auth even when a global
    token is also set."""
    tokens = {"esp32-001": ""}
    # Listed with empty token: no policy for that device, allow.
    assert _check_auth(None, "esp32-001", tokens, "") is True
    assert _check_auth("Bearer anything", "esp32-001", tokens, "") is True
    # But the global token still applies to OTHER devices.
    assert _check_auth("Bearer global", "esp32-002", tokens, "global") is True
    assert _check_auth("Bearer wrong", "esp32-002", tokens, "global") is False
