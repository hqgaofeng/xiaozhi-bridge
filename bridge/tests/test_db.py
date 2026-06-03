"""Direct unit tests for BridgeDB (V2 #4).

These tests bypass FastAPI and hit the database class directly.
This catches db-layer bugs (e.g. SQL NULL handling, ON CONFLICT
semantics) that the API-level tests in test_api.py might mask
because they only ever exercise the API contract.

Same singleton-reset pattern as test_api.py: a fresh on-disk db
per test via tmp_path + XIAOZHI_API__DB_PATH env, then close()
the process-level singleton between cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xiaozhi_bridge.api.db import BridgeDB, reset_db_for_tests


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Yield a freshly-opened BridgeDB; close on teardown."""
    db_path = tmp_path / "bridge.db"
    monkeypatch.setenv("XIAOZHI_API__DB_PATH", str(db_path))
    await reset_db_for_tests()
    d = BridgeDB()
    await d.connect()
    try:
        yield d
    finally:
        await d.close()
        await reset_db_for_tests()


# --- devices --


async def test_upsert_device_with_id(db: BridgeDB) -> None:
    await db.upsert_device("esp32-001")
    devices = await db.list_devices()
    assert len(devices) == 1
    assert devices[0]["id"] == "esp32-001"


async def test_upsert_device_twice_updates_last_seen(db: BridgeDB) -> None:
    """Same device_id twice → still 1 row, lastSeen refreshed."""
    await db.upsert_device("esp32-001")
    first = (await db.list_devices())[0]["lastSeen"]
    await db.upsert_device("esp32-001")
    rows = await db.list_devices()
    assert len(rows) == 1
    assert rows[0]["lastSeen"] >= first


async def test_upsert_device_unknown_id_falls_back(db: BridgeDB) -> None:
    """V2 #4 contract: device_id=None must NOT silently lose data.

    Background: in V2 #3, open_session() only calls upsert_device
    when device_id is truthy, which means a session opened without
    a Device-Id header would have no row in `devices` at all —
    making /api/devices always appear empty in real ESP32 use if
    the firmware forgot the header.

    V2 #4 makes open_session() pass through None; upsert_device
    stores it under the synthetic "unknown" id so the row exists.
    Real device rows are still keyed by their actual id.
    """
    await db.upsert_device(None)  # type: ignore[arg-type]
    devices = await db.list_devices()
    assert len(devices) == 1
    assert devices[0]["id"] == "unknown"


async def test_open_session_without_device_id_still_creates_unknown_row(
    db: BridgeDB,
) -> None:
    """End-to-end: open_session(device_id=None) → /api/devices has 'unknown'."""
    await db.open_session("sess-1", device_id=None)
    devices = await db.list_devices()
    assert len(devices) == 1
    assert devices[0]["id"] == "unknown"
    # The session row itself has device_id=NULL (foreign key is loose
    # — sessions.device_id is just a label, not enforced). We read
    # it directly because BridgeDB doesn't expose a list_sessions()
    # helper in V2 #3 (only list_devices / list_conversations / list_iot).
    assert db._conn is not None
    async with db._conn.execute(
        "SELECT device_id FROM sessions WHERE session_id = ?", ("sess-1",)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] is None


async def test_open_session_with_device_id_creates_real_row(
    db: BridgeDB,
) -> None:
    await db.open_session("sess-1", device_id="esp32-001")
    devices = await db.list_devices()
    assert len(devices) == 1
    assert devices[0]["id"] == "esp32-001"


# --- conversations ---


async def test_record_conversation_with_device_id(db: BridgeDB) -> None:
    # FK from conversations.device_id → devices.device_id, so we
    # need the device row to exist first (open_session upserts it).
    await db.open_session("sess-1", device_id="esp32-001")
    cid = await db.record_conversation(
        device_id="esp32-001",
        session_id="sess-1",
        stt_text="hello",
        assistant_text="hi",
    )
    assert cid > 0
    convos = await db.list_conversations(device_id="esp32-001")
    assert len(convos) == 1
    assert convos[0]["deviceId"] == "esp32-001"
    assert convos[0]["turns"][0]["text"] == "hello"
    assert convos[0]["turns"][1]["text"] == "hi"


async def test_list_conversations_filters_by_device(db: BridgeDB) -> None:
    await db.open_session("s1", device_id="esp32-001")
    await db.open_session("s2", device_id="esp32-002")
    await db.record_conversation("esp32-001", "s1", "a", "b")
    await db.record_conversation("esp32-002", "s2", "c", "d")
    assert len(await db.list_conversations(device_id="esp32-001")) == 1
    assert len(await db.list_conversations(device_id="esp32-002")) == 1
    assert len(await db.list_conversations()) == 2


async def test_record_conversation_null_device_is_stored(db: BridgeDB) -> None:
    """When firmware omits Device-Id, conversations still get saved
    (just with deviceId=''). They're not lost."""
    cid = await db.record_conversation(
        device_id=None, session_id="sess-1", stt_text="x", assistant_text="y"
    )
    assert cid > 0
    convos = await db.list_conversations()
    assert len(convos) == 1
    # The API serializes None device_id as "" so JS clients don't trip
    # on null (this is the same behavior the bridge already shows for
    # the V2 #3 e2e records).
    assert convos[0]["deviceId"] == ""
