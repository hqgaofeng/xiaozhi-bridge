"""Tests for the HTTP API (V2 #3).

We use FastAPI's TestClient which spins up the app in-process with
a thread-pool backend, so the lifespan events (db.connect / close) run.

Each test gets a fresh on-disk sqlite db at a tmp path so the
process-level singleton is reset between cases (via the autouse
fixture). This is how we keep the singleton clean without monkey-
patching the module — `reset_db_for_tests` closes + nulls it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xiaozhi_bridge.api import create_app
from xiaozhi_bridge.api.db import get_db, reset_db_for_tests


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "bridge.db"
    monkeypatch.setenv("XIAOZHI_API__DB_PATH", str(db_path))
    # Also clear the module-level singleton so connect() runs fresh.
    import asyncio
    asyncio.run(reset_db_for_tests())
    return db_path


@pytest.fixture
def client(tmp_db: Path) -> TestClient:
    app = create_app()
    with TestClient(app) as c:
        yield c
    # cleanup
    import asyncio
    asyncio.run(reset_db_for_tests())


# --- health ---

def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "0.2.2"}


# --- devices (empty by default; populated by integration tests) ---

def test_list_devices_empty(client: TestClient) -> None:
    r = client.get("/api/devices")
    assert r.status_code == 200
    assert r.json() == []


def test_get_device_404(client: TestClient) -> None:
    r = client.get("/api/devices/nonexistent")
    assert r.status_code == 404


def test_reboot_device_501(client: TestClient) -> None:
    r = client.post("/api/devices/foo/reboot")
    assert r.status_code == 501


# --- V2 #4: GET /api/devices/{id}/conversations --


def test_device_conversations_empty(client: TestClient) -> None:
    r = client.get("/api/devices/esp32-001/conversations")
    assert r.status_code == 200
    assert r.json() == []


def test_device_conversations_seeded(client: TestClient) -> None:
    """V2 #4: write conversations for two devices, verify the new
    route filters by device and respects ?limit."""
    import asyncio

    from xiaozhi_bridge.api.db import get_db

    async def _seed() -> None:
        # We have to reach the same db the TestClient app is using.
        # The client fixture already opened it; we just reuse the
        # process-level singleton.
        d = get_db()
        await d.open_session("s1", device_id="esp32-001")
        await d.open_session("s2", device_id="esp32-001")
        await d.open_session("s3", device_id="esp32-002")
        await d.record_conversation("esp32-001", "s1", "hi", "hello")
        await d.record_conversation("esp32-001", "s2", "weather", "sunny")
        await d.record_conversation("esp32-002", "s3", "music", "playing")

    asyncio.run(_seed())

    r = client.get("/api/devices/esp32-001/conversations")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all(c["deviceId"] == "esp32-001" for c in data)

    r2 = client.get("/api/devices/esp32-002/conversations")
    assert len(r2.json()) == 1
    assert r2.json()[0]["deviceId"] == "esp32-002"


def test_device_conversations_limit(client: TestClient) -> None:
    """The new ?limit query param clamps the result set."""
    import asyncio

    async def _seed() -> None:
        d = get_db()
        await d.open_session("s1", device_id="esp32-001")
        for i in range(5):
            await d.record_conversation(
                "esp32-001", "s1", f"q{i}", f"a{i}"
            )

    asyncio.run(_seed())

    r = client.get("/api/devices/esp32-001/conversations?limit=2")
    assert r.status_code == 200
    assert len(r.json()) == 2


# --- conversations ---

def test_list_conversations_empty(client: TestClient) -> None:
    r = client.get("/api/conversations")
    assert r.status_code == 200
    assert r.json() == []


def test_conversation_limit_validation(client: TestClient) -> None:
    r = client.get("/api/conversations?limit=999")
    assert r.status_code == 400


def test_get_conversation_bad_id(client: TestClient) -> None:
    r = client.get("/api/conversations/notanumber")
    assert r.status_code == 400


def test_get_conversation_404(client: TestClient) -> None:
    r = client.get("/api/conversations/9999")
    assert r.status_code == 404


# --- IoT ---

def test_iot_seeded(client: TestClient) -> None:
    """First open of a fresh db should auto-seed 2 demo IoT devices."""
    r = client.get("/api/iot")
    assert r.status_code == 200
    devices = r.json()
    assert len(devices) == 2
    assert {d["id"] for d in devices} == {"light-1", "switch-1"}


def test_iot_control_updates_state(client: TestClient) -> None:
    r = client.post("/api/iot/light-1/control", json={"action": "on", "value": 80})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "light-1"
    assert body["state"]["action"] == "on"
    assert body["state"]["value"] == 80


def test_iot_control_404(client: TestClient) -> None:
    r = client.post("/api/iot/nope/control", json={"action": "on"})
    assert r.status_code == 404


def test_iot_control_validation(client: TestClient) -> None:
    r = client.post("/api/iot/light-1/control", json={"value": 10})
    assert r.status_code == 400


# --- config ---

def test_config_get_empty(client: TestClient) -> None:
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json() == {}


def test_config_patch_and_get(client: TestClient) -> None:
    r = client.patch("/api/config", json={"theme": "dark", "lang": "zh"})
    assert r.status_code == 200
    assert r.json() == {"theme": "dark", "lang": "zh"}
    r2 = client.get("/api/config")
    assert r2.json() == {"theme": "dark", "lang": "zh"}


def test_config_patch_empty_body_400(client: TestClient) -> None:
    r = client.patch("/api/config", json={})
    assert r.status_code == 400
