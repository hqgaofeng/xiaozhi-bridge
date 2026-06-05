"""V2 #8 minimal: xiaozhi-esp32 OTA endpoint.

The xiaozhi-esp32 firmware, on every boot, does:

    GET <nvs.url>

where nvs.url is the OTA URL. It expects a JSON like:

    {
        "websocket": {"url": "wss://server/xiaozhi/v1/"},
        "server_time": {...},
        "firmware": {"version": "2.2.6", "url": ""}
        # NO activation section — V2 #8.1 fix
    }

If this endpoint is missing or returns wrong shape, the firmware
falls back to the default tenclass.net OTA URL — bypassing our
bridge entirely (we hit this in the V2 #8 bring-up: the device
showed "connected to api.tenclass.net" instead of our server).

V2 #8.1 CRITICAL: NO 'activation' section in response. The
xiaozhi-esp32 main/ota.cc CheckVersion() reads:

    cJSON* code = cJSON_GetObjectItem(activation, "code");
    if (cJSON_IsString(code)) {
        activation_code_ = code->valuestring;
        has_activation_code_ = true;   ← TRAP!
    }

Then CheckNewVersion() at line ~446:
    if (!HasActivationCode() && !HasActivationChallenge()) { break; }

With has_activation_code_=true → no break → ShowActivationCode
shows "请到控制台添加设备, 验证码 00:00:00" → 10x Activate() fails
→ infinite while(true) loop. Device never reaches InitializeProtocol.

V2 #8.1 fix: omit the entire 'activation' section → both flags
stay false → outer while breaks → InitializeProtocol runs → idle
→ waits for wake word → OpenAudioChannel() → bridge 8000 hello.

These tests pin the minimal contract so we don't regress.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from xiaozhi_bridge.api.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_ota_endpoint_returns_websocket_url() -> None:
    """V2 #8 minimal: esp32 needs websocket.url in OTA response."""
    r = _client().post(
        "/api/xiaozhi/ota/",
        json={
            "version": 2,
            "board": "my-custom-wifi-lcd",
            "mac_address": "58:e6:c5:6b:9b:54",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "websocket" in body
    assert "url" in body["websocket"]
    url = body["websocket"]["url"]
    # must be a wss:// URL pointing at our bridge (or localhost in dev)
    assert url.startswith("wss://") or url.startswith("ws://")
    # must point to /xiaozhi/v1/ (or local-equivalent) — that's the
    # path nginx proxies to the bridge WS server on 8000
    assert "/xiaozhi/v1/" in url


def test_ota_endpoint_returns_required_keys() -> None:
    """V2 #8.1: esp32 reads server_time, firmware — NO activation section.

    The activation section is intentionally OMITTED. If we return
    {"code": "00:00:00", "message": "..."}, the device enters
    ShowActivationCode infinite loop and never reaches InitializeProtocol.
    See xiaozhi-esp32 main/ota.cc CheckVersion() + CheckNewVersion().
    """
    r = _client().post("/api/xiaozhi/ota/", json={})
    assert r.status_code == 200
    body = r.json()
    for key in ("websocket", "server_time", "firmware"):
        assert key in body, f"missing OTA key: {key}"

    # V2 #8.1 CRITICAL: NO activation section.
    assert "activation" not in body, (
        "activation section is a TRAP — device enters infinite "
        "ShowActivationCode loop. See xiaozhi-esp32 main/ota.cc."
    )

    st = body["server_time"]
    assert "timestamp" in st
    assert "timezone" in st
    assert "timezone_offset_minutes" in st
    # offset should match Asia/Shanghai (8h)
    assert st["timezone_offset_minutes"] == 8 * 60

    fw = body["firmware"]
    assert "version" in fw
    # minimal version: empty url = "stay on current firmware"
    assert fw["url"] == ""


def test_ota_endpoint_accepts_post_with_device_info() -> None:
    """V2 #8 minimal: esp32 sends device info as POST body.

    The Ota::CheckVersion() source in ota.cc uses
    `method = data.length() > 0 ? "POST" : "GET"`. Since the device
    always sends GetSystemInfoJson() (non-empty), it always POSTs.
    """
    device_info = {
        "version": 2,
        "flash_size": 16777216,
        "psram_size": 8388608,
        "minimum_free_heap_size": 102400,
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "board": "my-custom-wifi-lcd",
        "language": "zh-CN",
    }
    r = _client().post("/api/xiaozhi/ota/", json=device_info)
    assert r.status_code == 200
    body = r.json()
    assert body["websocket"]["url"].startswith("wss://")
    # server_time.timestamp should be in ms (not seconds) — esp32 ota.cc
    # divides by 1000, so a 13-digit unix ms timestamp is expected
    assert body["server_time"]["timestamp"] > 1_000_000_000_000


def test_ota_endpoint_works_without_trailing_slash() -> None:
    """V2 #8 minimal: some esp32 builds strip the trailing slash.

    The @app.get() decorator was registered for both paths to be
    safe (FastAPI 307-redirects by default, but we want the device
    to hit the same handler in one round trip).
    """
    r = _client().post("/api/xiaozhi/ota", json={})
    assert r.status_code == 200
    assert "websocket" in r.json()


def test_ota_endpoint_supports_get_fallback() -> None:
    """V2 #8 minimal: some forks/older builds send GET (no body).

    If device info is empty, ota.cc sends GET instead of POST. We
    support both for max compatibility.
    """
    r = _client().get("/api/xiaozhi/ota/")
    assert r.status_code == 200
    body = r.json()
    assert body["websocket"]["url"].startswith("wss://")
