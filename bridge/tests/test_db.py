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
    (under the synthetic "unknown" device_id, the same bucket
    upsert_device writes to). They're not lost and the new
    /api/devices/unknown/conversations route can find them.

    The FK from conversations.device_id → devices.device_id means
    we need the "unknown" row to exist first; in production the
    bridge's open_session() does this for us. Here we call
    open_session() to mirror the real flow.
    """
    await db.open_session("sess-1", device_id=None)
    cid = await db.record_conversation(
        device_id=None, session_id="sess-1", stt_text="x", assistant_text="y"
    )
    assert cid > 0
    convos = await db.list_conversations()
    assert len(convos) == 1
    # record_conversation applies the same effective_id rule as
    # upsert_device: None → "unknown" so the row is queryable.
    assert convos[0]["deviceId"] == "unknown"
    # And the unknown bucket is queryable.
    unknown_convos = await db.list_conversations(device_id="unknown")
    assert len(unknown_convos) == 1



# --- V2 #6: device metadata (name/notes/room) ---


async def test_upsert_device_creates_row_with_null_metadata(
    db: BridgeDB,
) -> None:
    """V2 #6: a fresh upsert must not invent a name/notes/room.

    The list_devices() fallback (name → device_id) is what
    surfaces a friendly default to the UI; the DB itself stays
    sparse so we can distinguish 'never set' from 'set to ""'.
    """
    await db.upsert_device("esp32-001")
    assert db._conn is not None
    async with db._conn.execute(
        "SELECT name, notes, room FROM devices WHERE device_id = ?",
        ("esp32-001",),
    ) as cur:
        row = await cur.fetchone()
    assert row == (None, None, None)


async def test_update_device_partial_preserves_other_fields(
    db: BridgeDB,
) -> None:
    """V2 #6: PATCH semantics — only touch what the client sent."""
    await db.upsert_device("esp32-001")
    # Set all three first so we can verify only the named one moves.
    assert await db.update_device(
        "esp32-001", name="客厅", notes="主控", room="客厅"
    )
    # Now update only name; notes & room must survive.
    assert await db.update_device("esp32-001", name="主卧")
    d = await db.get_device("esp32-001")
    assert d is not None
    assert d["name"] == "主卧"
    assert d["notes"] == "主控"
    assert d["room"] == "客厅"


async def test_update_device_empty_string_clears_field(
    db: BridgeDB,
) -> None:
    """V2 #6: PATCH with '' explicitly clears the field; the
    response surfaces it as '' (not the device_id fallback)."""
    await db.upsert_device("esp32-001")
    await db.update_device("esp32-001", name="客厅")
    d_before = await db.get_device("esp32-001")
    assert d_before is not None and d_before["name"] == "客厅"
    assert await db.update_device("esp32-001", name="")
    d = await db.get_device("esp32-001")
    assert d is not None
    # '' is the 'cleared' state, not the device_id fallback.
    assert d["name"] == ""


async def test_update_device_no_op_returns_true_if_exists(
    db: BridgeDB,
) -> None:
    """V2 #6: an empty PATCH (caller passed no fields) is a no-op
    for the row but must still report existence truthfully so
    the API layer can map 'device not found' → 404."""
    await db.upsert_device("esp32-001")
    # Pass nothing — all three are None.
    assert await db.update_device("esp32-001") is True
    assert await db.update_device("nonexistent") is False


async def test_update_device_missing_returns_false(db: BridgeDB) -> None:
    await db.upsert_device("esp32-001")
    assert await db.update_device("esp32-001", name="x") is True
    assert await db.update_device("ghost", name="x") is False


async def test_list_devices_falls_back_to_id_when_name_unset(
    db: BridgeDB,
) -> None:
    """V2 #6 contract: legacy rows from v0.2.0~v0.2.5 have NULL
    name. The API response must use the device_id as the visible
    name so existing web clients keep working without a data
    migration."""
    await db.upsert_device("esp32-001")
    devices = await db.list_devices()
    assert len(devices) == 1
    # The friendly name is the device_id when the user hasn't
    # set one (and the DB stores NULL).
    assert devices[0]["name"] == "esp32-001"


async def test_list_devices_returns_metadata_when_set(
    db: BridgeDB,
) -> None:
    await db.upsert_device("esp32-001")
    await db.update_device(
        "esp32-001", name="客厅音箱", notes="主控", room="客厅"
    )
    devices = await db.list_devices()
    assert len(devices) == 1
    d = devices[0]
    assert d["name"] == "客厅音箱"
    assert d["notes"] == "主控"
    assert d["room"] == "客厅"


async def test_get_device_sql_lookup(db: BridgeDB) -> None:
    """V2 #6: get_device goes straight to SQL (no full table
    scan). Verifies the new WHERE-clause code path returns the
    right row for a specific id."""
    await db.upsert_device("esp32-001")
    await db.upsert_device("esp32-002")
    d = await db.get_device("esp32-002")
    assert d is not None
    assert d["id"] == "esp32-002"
    d_missing = await db.get_device("nonexistent")
    assert d_missing is None


async def test_delete_device_cascades_conversations_to_null(
    db: BridgeDB,
) -> None:
    """V2 #6: deleting a device must NOT destroy its conversation
    history. The FK ON DELETE SET NULL on conversations.device_id
    moves the row to the 'unknown' bucket so /api/conversations
    still returns it (now grouped under 'unknown')."""
    await db.open_session("sess-1", device_id="esp32-001")
    cid = await db.record_conversation(
        device_id="esp32-001",
        session_id="sess-1",
        stt_text="hi",
        assistant_text="hello",
    )
    assert cid > 0
    assert await db.delete_device("esp32-001") is True
    # The device row is gone.
    assert await db.get_device("esp32-001") is None
    # The conversation still exists, re-parented to NULL.
    assert db._conn is not None
    async with db._conn.execute(
        "SELECT device_id FROM conversations WHERE id = ?", (cid,)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] is None


async def test_delete_device_missing_returns_false(
    db: BridgeDB,
) -> None:
    assert await db.delete_device("ghost") is False
    # Deleting the same id twice is also False the second time.
    await db.upsert_device("esp32-001")
    assert await db.delete_device("esp32-001") is True
    assert await db.delete_device("esp32-001") is False


async def test_migrate_adds_columns_to_legacy_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V2 #6 migration: an existing v0.2.5 db (4 columns, no
    name/notes/room) must be upgraded in place when connect()
    is called — no manual SQL needed, no data loss."""
    import aiosqlite

    db_path = tmp_path / "legacy.db"
    # Hand-craft a v0.2.5-shaped devices table and a row.
    async with aiosqlite.connect(db_path) as legacy:
        await legacy.executescript(
            "CREATE TABLE devices ("
            "  device_id TEXT PRIMARY KEY,"
            "  first_seen REAL NOT NULL,"
            "  last_seen REAL NOT NULL,"
            "  auth_token TEXT"
            ");"
        )
        await legacy.execute(
            "INSERT INTO devices VALUES('esp32-old', 1.0, 2.0, NULL);"
        )
        await legacy.commit()
    # Now point our BridgeDB at the same file and connect.
    monkeypatch.setenv("XIAOZHI_API__DB_PATH", str(db_path))
    await reset_db_for_tests()
    d = BridgeDB()
    await d.connect()
    try:
        # The legacy row must still be there.
        got = await d.get_device("esp32-old")
        assert got is not None
        # The new columns must be present and NULL.
        assert d._conn is not None
        async with d._conn.execute(
            "SELECT name, notes, room FROM devices WHERE device_id = ?",
            ("esp32-old",),
        ) as cur:
            row = await cur.fetchone()
        assert row == (None, None, None)
        # And the friendly-name fallback still works on the
        # legacy row.
        assert got["name"] == "esp32-old"
    finally:
        await d.close()
        await reset_db_for_tests()
