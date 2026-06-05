"""FastAPI app for the xiaozhi-bridge HTTP API (V2 #3).

Routes (mounted under /api, see create_app):

    GET    /api/health              liveness probe
    GET    /api/devices             list devices (joined with active session)
    GET    /api/devices/{id}        one device
    POST   /api/devices/{id}/reboot placeholder (V1: returns 501)
    GET    /api/conversations       list recent turns
    GET    /api/conversations/{id}  one conversation
    GET    /api/iot                 list IoT devices
    POST   /api/iot/{id}/control    control an IoT device (V1: updates db only)
    GET    /api/config              get stored config (V1: empty dict)
    PATCH  /api/config              set a config key (V1: stored but not applied)
    GET    /api/logs/stream         SSE stream of structlog events (V1: empty)

The CORS middleware lets the Vite dev server (port 3000) call us
without preflight pain. In production the same-origin nginx proxy
hides this.

To run standalone:
    python -m xiaozhi_bridge.api --port 8001
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .db import BridgeDB, get_db

# --- App factory ---

def create_app() -> FastAPI:
    """Build a fresh FastAPI app. Tests use this directly."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        db = get_db()
        await db.connect()
        try:
            yield
        finally:
            # Shutdown
            await db.close()

    app = FastAPI(
        title="xiaozhi-bridge API",
        version="0.2.13",
        description="HTTP API for the xiaozhi-bridge WebSocket bridge.",
        lifespan=lifespan,
    )

    # CORS for Vite dev server (port 3000). In prod nginx proxies
    # /api/ directly so CORS is moot, but enabling it doesn't hurt.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://jarvis.beallen.top",
            "http://localhost:5180",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routes(app)
    return app


# --- Routes (defined at module level so the linter sees them; the
#     function still takes `app` to bind paths to a specific instance).

def _register_routes(app: FastAPI) -> None:
    db_dep = Depends(get_db)

    # --- health ---

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "version": "0.2.13"}

    # --- devices ---

    @app.get("/api/devices")
    async def list_devices(db: BridgeDB = db_dep) -> list[dict]:
        return await db.list_devices()

    @app.get("/api/devices/{device_id}")
    async def get_device(device_id: str, db: BridgeDB = db_dep) -> dict:
        d = await db.get_device(device_id)
        if d is None:
            raise HTTPException(status_code=404, detail="device not found")
        return d

    @app.patch("/api/devices/{device_id}")
    async def update_device(
        device_id: str,
        body: dict,
        db: BridgeDB = db_dep,
    ) -> dict:
        """V2 #6: partial update of friendly metadata.

        Body shape (all keys optional, but at least one required):
            {"name":  "...", "notes": "...", "room": "..."}
        Empty string clears the field; omitted key leaves it untouched.

        Returns 200 with the updated device record on success.
        Returns 404 if the device_id doesn't exist.
        Returns 422 if the body is empty (a no-op PATCH is almost
        always a client bug, and surfacing it as 422 is clearer
        than a silent 200).
        """
        # Whitelist accepted keys — reject unknown fields so the
        # client gets a clear 422 instead of silently dropping them.
        allowed = {"name", "notes", "room"}
        bad = set(body) - allowed
        if bad:
            raise HTTPException(
                status_code=422,
                detail=f"unknown field(s): {sorted(bad)}; allowed: {sorted(allowed)}",
            )
        if not body:
            raise HTTPException(
                status_code=422,
                detail=f"empty PATCH body; provide at least one of {sorted(allowed)}",
            )
        # Pydantic isn't required for such a small body shape —
        # a dict + key whitelist gives the same protection with
        # less import noise. If the body ever grows past 5 fields
        # we should switch to a pydantic model.
        name = body.get("name")
        notes = body.get("notes")
        room = body.get("room")
        ok = await db.update_device(
            device_id, name=name, notes=notes, room=room
        )
        if not ok:
            raise HTTPException(status_code=404, detail="device not found")
        # Re-fetch so the response reflects the persisted state
        # (and the `name → device_id fallback` in list_devices()
        # is applied consistently with the list endpoint).
        d = await db.get_device(device_id)
        assert d is not None  # we just updated it
        return d

    @app.delete("/api/devices/{device_id}")
    async def delete_device(
        device_id: str, db: BridgeDB = db_dep
    ) -> dict:
        """V2 #6: remove a device and cascade its FKs.

        Conversations and sessions for this device get their
        device_id set to NULL (per FK ON DELETE SET NULL), so
        /api/conversations still returns them — they're not lost,
        they just become 'orphan' rows visible via the 'unknown'
        bucket in /api/devices.

        Returns 200 with {"deleted": device_id} on success.
        Returns 404 if the device_id didn't exist.

        We intentionally do NOT support deleting the synthetic
        'unknown' bucket — it's a fallback for firmware that
        forgot the Device-Id header and removing it would make
        /api/devices look artificially clean.
        """
        if device_id == "unknown":
            raise HTTPException(
                status_code=400,
                detail="the 'unknown' bucket cannot be deleted "
                "(it's the fallback for missing Device-Id headers)",
            )
        ok = await db.delete_device(device_id)
        if not ok:
            raise HTTPException(status_code=404, detail="device not found")
        return {"deleted": device_id}

    @app.post("/api/devices/{device_id}/reboot")
    async def reboot_device(device_id: str) -> dict:
        # V1 doesn't speak a reboot command to devices; surface a
        # 501 so the UI shows a clear "not implemented in V1" state.
        # V2 will send an `abort` over WebSocket + a system message.
        raise HTTPException(
            status_code=501,
            detail="device reboot not implemented in V1; V2 will add WebSocket-triggered reboot",
        )

    @app.get("/api/devices/{device_id}/conversations")
    async def list_device_conversations(
        device_id: str,
        limit: int = Query(50, ge=1, le=500),
        db: BridgeDB = db_dep,
    ) -> list[dict]:
        """List conversations for one device, newest first.

        V2 #4 addition so the Devices page can show a per-device
        history without forcing the client to fetch all conversations
        and filter. The "unknown" device is the synthetic bucket for
        firmware that didn't send a Device-Id header.
        """
        return await db.list_conversations(device_id=device_id, limit=limit)

    # --- conversations ---

    @app.get("/api/conversations")
    async def list_conversations(
        # web/ side uses `deviceId` (camelCase) — alias keeps the
        # HTTP contract stable while letting the python param be
        # snake_case (pep8 / ruff happy).
        device_id: str | None = Query(default=None, alias="deviceId"),
        limit: int = 50,
        db: BridgeDB = db_dep,
    ) -> list[dict]:
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be 1..500")
        return await db.list_conversations(device_id=device_id, limit=limit)

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, db: BridgeDB = db_dep) -> dict:
        try:
            cid = int(conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="id must be an integer") from None
        c = await db.get_conversation(cid)
        if c is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return c

    # --- IoT ---

    @app.get("/api/iot")
    async def list_iot(db: BridgeDB = db_dep) -> list[dict]:
        return await db.list_iot_devices()

    @app.post("/api/iot/{device_id}/control")
    async def control_iot(
        device_id: str,
        body: dict[str, Any],
        db: BridgeDB = db_dep,
    ) -> dict:
        action = body.get("action")
        value = body.get("value")
        if not isinstance(action, str):
            raise HTTPException(status_code=400, detail="action must be a string")
        # V1: this only persists a fake state change in the DB. V2
        # will route to the matching MCP tool on the bridge side
        # (or to openclaw's IoT platform integration).
        new_state: dict[str, Any] = {
            "action": action,
            "value": value,
            "ts": __import__("time").time(),
        }
        ok = await db.update_iot_state(device_id, new_state)
        if not ok:
            raise HTTPException(status_code=404, detail="iot device not found")
        devices = await db.list_iot_devices()
        for d in devices:
            if d["id"] == device_id:
                return d
        raise HTTPException(status_code=500, detail="state updated but device vanished")

    # --- config ---

    @app.get("/api/config")
    async def get_config(db: BridgeDB = db_dep) -> dict:
        return await db.get_config()

    @app.patch("/api/config")
    async def patch_config(body: dict[str, Any], db: BridgeDB = db_dep) -> dict:
        if not isinstance(body, dict) or not body:
            raise HTTPException(status_code=400, detail="body must be a non-empty object")
        for k, v in body.items():
            if not isinstance(k, str):
                raise HTTPException(status_code=400, detail="keys must be strings")
            await db.set_config(k, v)
        # V1: stored, not applied to the running bridge. V2 will
        # wire this to live config reload (see V2 #3 follow-up notes).
        return await db.get_config()

    # --- logs (SSE) ---

    @app.get("/api/logs/stream")
    async def stream_logs() -> StreamingResponse:
        """V1: emits a heartbeat every 2s. V2 will tail structlog.

        Real structlog tailing needs a tail-style reader (we don't
        write to a file in V1; logs go to stdout in JSON, picked up
        by docker compose logs / journalctl on the host). V2 will
        add a file-based log + watchdog.
        """
        async def gen():
            import time
            while True:
                payload = {
                    "ts": time.time(),
                    "level": "INFO",
                    "msg": "log stream heartbeat (V1: real structlog tailing is V2 work)",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(2.0)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # --- xiaozhi-esp32 OTA endpoint (V2 #8 minimal) ---
    # esp32 firmware boots → POST /api/xiaozhi/ota/ with device info
    # JSON body → we return config including the WS server URL.
    # esp32 then WebSocket-Connects the URL we told it.
    #
    # Source: xiaozhi-esp32 main/ota.cc ::Ota::CheckVersion()
    #   - Reads NVS `wifi.ota_url` (or CONFIG_OTA_URL fallback)
    #   - Sends device info JSON body via POST
    #   - Parses response, writes `websocket` section to NVS namespace "websocket"
    #   - The websocket_protocol then reads websocket.url from NVS "websocket"
    #     namespace — which is how the firmware picks up our WS URL on reboot.
    @app.post("/api/xiaozhi/ota/")
    @app.post("/api/xiaozhi/ota")
    @app.get("/api/xiaozhi/ota/")
    @app.get("/api/xiaozhi/ota")
    async def ota_check(request_body: dict | None = None) -> dict:
        """V2 #8 minimal OTA endpoint: tells the device to WS-connect us.

        The esp32 sends a body like:
          {
            "version": 2,
            "flash_size": 16777216,
            "psram_size": 8388608,
            "board": "my-custom-wifi-lcd",
            "mac_address": "58:e6:c5:6b:9b:54",
            "language": "zh-CN"
          }
        We don't validate it in V2 #8 minimal — just log it and respond
        with the WS URL. The device's websocket_protocol.cc will then
        read `websocket.url` from NVS and Connect.
        """
        import logging
        import time

        log = logging.getLogger("xiaozhi_bridge.ota")

        # V2 #8 minimal: log device info (we'll use it for auth in V2 #8.1)
        if request_body:
            mac = request_body.get("mac_address", "unknown")
            board = request_body.get("board", "unknown")
            flash = request_body.get("flash_size", "?")
            log.info(
                "OTA check from board=%s mac=%s flash=%s",
                board, mac, flash,
            )

        # V2 #8.1 fix: REMOVE the activation section entirely.
        #
        # Why: xiaozhi-esp32 main/ota.cc CheckVersion() reads:
        #   cJSON* code = cJSON_GetObjectItem(activation, "code");
        #   if (cJSON_IsString(code)) {
        #       activation_code_ = code->valuestring;
        #       has_activation_code_ = true;   ← "00:00:00" triggers this
        #   }
        # Then CheckNewVersion() at line ~446:
        #   if (!HasActivationCode() && !HasActivationChallenge()) { break; }
        # has_activation_code_=true → no break → ShowActivationCode
        # shows "请到 xiaozhi.me 添加设备, 验证码 00:00:00" → 10x
        # Activate() returns ESP_FAIL (no challenge) → infinite while loop.
        #
        # V2 #8.0 had `"code": "00:00:00"` which traps the device.
        # V2 #8.1: omit activation entirely → both flags stay false →
        # outer while breaks → InitializeProtocol runs → idle → waits
        # for wake word → OpenAudioChannel() → bridge 8000 hello.
        return {
            "websocket": {
                "url": "wss://jarvis.beallen.top/xiaozhi/v1/",
            },
            "server_time": {
                "timestamp": int(time.time() * 1000),
                "timezone": "Asia/Shanghai",
                "timezone_offset_minutes": 8 * 60,
            },
            "firmware": {
                "version": "2.2.6",
                "url": "",
            },
        }


# Default app for `uvicorn xiaozhi_bridge.api.main:app`
# IMPORTANT: this must come AFTER _register_routes is defined (see
# the V0.2.0 dev loop where I got the order wrong once and
# NameError'd). Module-level import of create_app() from __init__.py
# triggers this line; it is safe because _register_routes is defined
# above in the same module.
app = create_app()


# --- CLI ---

def main() -> int:
    parser = argparse.ArgumentParser(prog="xiaozhi-bridge-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--reload", action="store_true", help="auto-reload (dev only)")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "xiaozhi_bridge.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
