"""SQLite persistence layer for the bridge HTTP API (V2 #3).

Schema (v0.2.0):

    devices           -- one row per device_id ever seen
    sessions          -- one row per websocket session (per connection)
    conversations     -- one row per device turn-cycle (listen start..stop)
    conversation_turns -- user/assistant text within a conversation
    iot_devices       -- discovered/registered IoT devices (V2 follow-up)
    iot_state         -- last known state per iot device

Why aiosqlite (not sqlite3): the API runs under uvicorn's event loop;
sync sqlite3 would block the loop on every write. aiosqlite delegates
to a background thread so each call is non-blocking from FastAPI's
POV.

WAL mode is enabled for concurrent reads (API reads while bridge
writes); busy_timeout avoids spurious SQLITE_BUSY errors when both
processes hit the same row at startup.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

# --- Schema ---

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,
    first_seen    REAL NOT NULL,
    last_seen     REAL NOT NULL,
    auth_token    TEXT,
    -- V2 #6: user-friendly metadata. All nullable so legacy rows
    -- (v0.2.0~v0.2.5) and the synthetic 'unknown' bucket read
    -- cleanly. list_devices() falls back to device_id when name
    -- is NULL so existing clients keep working.
    name          TEXT,
    notes         TEXT,
    room          TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    device_id     TEXT,
    created_at    REAL NOT NULL,
    closed_at     REAL,
    last_state    TEXT NOT NULL DEFAULT 'idle',
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_device ON sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(closed_at) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT,
    session_id    TEXT,
    started_at    REAL NOT NULL,
    ended_at      REAL,
    stt_text      TEXT,           -- what the user said
    assistant_text TEXT,          -- what the LLM said
    llm_status    TEXT,           -- 'ok' | 'error' | 'fallback'
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_device ON conversations(device_id);
CREATE INDEX IF NOT EXISTS idx_conversations_started ON conversations(started_at DESC);

CREATE TABLE IF NOT EXISTS iot_devices (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,  -- light | switch | fan | ac | curtain | sensor | other
    room          TEXT,
    online        INTEGER NOT NULL DEFAULT 1,
    state_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS config_kv (
    key           TEXT PRIMARY KEY,
    value_json    TEXT NOT NULL,
    updated_at    REAL NOT NULL
);
"""


# --- Default DB path ---

def default_db_path() -> Path:
    """Return the default DB path.

    Honors $XIAOZHI_API__DB_PATH (so docker-compose can mount a
    persistent volume). Falls back to /app/data/bridge.db in the
    container (mounted from a named volume in compose), or
    ./bridge.db in dev.
    """
    env = os.environ.get("XIAOZHI_API__DB_PATH")
    if env:
        return Path(env)
    # Production layout: /app/data/bridge.db (volume-mounted in compose)
    prod = Path("/app/data/bridge.db")
    if prod.parent.exists():
        return prod
    return Path("./bridge.db")


# --- Repository ---

class BridgeDB:
    """Thin aiosqlite wrapper for the bridge API.

    Connection is created lazily on first use; close() releases it.
    Methods are async (yield-friendly for FastAPI route handlers).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        # V2 #6: light migrations for legacy DBs (v0.2.0~v0.2.5)
        # that predate the devices.name/notes/room columns. Idempotent
        # — checks PRAGMA table_info first. SQLite ADD COLUMN is a
        # metadata-only op, safe to run on a hot db.
        await self._migrate()
        # Seed a couple of demo IoT devices if the table is empty
        # (lets the admin console have something to show pre-V2).
        await self._seed_demo_iot_if_empty()

    async def _migrate(self) -> None:
        """Idempotent column adds for legacy DBs (V2 #6).

        Why not a full migration framework (alembic etc.)?
        We have 1 schema, 1 app, 2 processes (bridge + api). A simple
        'if column missing, ADD COLUMN' check is enough and keeps the
        codebase free of alembic.ini / env.py / revision files.
        """
        assert self._conn is not None
        async with self._conn.execute("PRAGMA table_info(devices)") as cur:
            existing = {row[1] for row in await cur.fetchall()}
        additions: list[tuple[str, str]] = [
            ("name", "TEXT"),
            ("notes", "TEXT"),
            ("room", "TEXT"),
        ]
        for col, decl in additions:
            if col not in existing:
                # SQLite forbids DEFAULT for ADD COLUMN of TEXT NOT NULL,
                # but we want NULLs anyway (legacy rows have no friendly
                # name; list_devices() falls back to device_id).
                await self._conn.execute(
                    f"ALTER TABLE devices ADD COLUMN {col} {decl}"
                )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _seed_demo_iot_if_empty(self) -> None:
        if self._conn is None:
            return
        async with self._conn.execute("SELECT COUNT(*) FROM iot_devices") as cur:
            (n,) = await cur.fetchone()
        if n:
            return
        await self._conn.executemany(
            "INSERT INTO iot_devices(id, name, type, room, online, state_json) "
            "VALUES(?, ?, ?, ?, 1, ?)",
            [
                ("light-1", "客厅灯", "light", "客厅", json.dumps({"on": False, "brightness": 0})),
                ("switch-1", "卧室开关", "switch", "卧室", json.dumps({"on": False})),
            ],
        )
        await self._conn.commit()

    # --- devices ---

    async def upsert_device(
        self, device_id: str | None, auth_token: str | None = None
    ) -> None:
        # V2 #4: a missing Device-Id header (firmware forgot to set it)
        # is stored under the synthetic "unknown" id so the row still
        # exists in /api/devices. This way "device lost in the void"
        # failures are visible instead of silent.
        effective_id = device_id or "unknown"
        assert self._conn is not None
        now = time.time()
        await self._conn.execute(
            "INSERT INTO devices(device_id, first_seen, last_seen, auth_token) "
            "VALUES(?, ?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET "
            "  last_seen = excluded.last_seen, "
            "  auth_token = COALESCE(excluded.auth_token, devices.auth_token)",
            (effective_id, now, now, auth_token),
        )
        await self._conn.commit()

    async def list_devices(self) -> list[dict]:
        assert self._conn is not None
        # Join latest open session for the live state. V2 #6: also
        # pull name/notes/room so the API surfaces user-friendly
        # metadata in the response (web reads these for the
        # Devices page detail card).
        sql = """
        SELECT d.device_id, d.first_seen, d.last_seen,
               d.name, d.notes, d.room,
               s.session_id, s.last_state, s.created_at
        FROM devices d
        LEFT JOIN (
            SELECT device_id, session_id, last_state, created_at
            FROM sessions
            WHERE closed_at IS NULL
        ) s ON s.device_id = d.device_id
        ORDER BY d.last_seen DESC
        """
        async with self._conn.execute(sql) as cur:
            rows = await cur.fetchall()
        out = []
        for row in rows:
            (
                device_id,
                _first_seen,
                last_seen,
                name,
                notes,
                room,
                sid,
                last_state,
                _created_at,
            ) = row
            state = "offline" if sid is None else last_state
            out.append(
                {
                    "id": device_id,
                    "mac": device_id,  # V2: real MAC from header
                    # V2 #6: friendly name falls back to device_id
                    # when unset (legacy rows from v0.2.0-v0.2.5
                    # have NULL name; web shows id as a stable
                    # identity anchor even before the user renames).
                    "name": name if name is not None else device_id,
                    "notes": notes or "",
                    "room": room or "",
                    "state": state,
                    "lastSeen": last_seen,
                    "sessionId": sid,
                }
            )
        return out

    async def get_device(self, device_id: str) -> dict | None:
        # V2 #6: SQL-side WHERE instead of Python-side filter —
        # O(1) lookup vs O(N) full-table scan. The bridge's
        # `unknown` synthetic bucket also lives in `devices`, so
        # this works for it too.
        assert self._conn is not None
        sql = """
        SELECT d.device_id, d.first_seen, d.last_seen,
               d.name, d.notes, d.room,
               s.session_id, s.last_state, s.created_at
        FROM devices d
        LEFT JOIN (
            SELECT device_id, session_id, last_state, created_at
            FROM sessions
            WHERE closed_at IS NULL
        ) s ON s.device_id = d.device_id
        WHERE d.device_id = ?
        """
        async with self._conn.execute(sql, (device_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        (
            dev_id,
            _first_seen,
            last_seen,
            name,
            notes,
            room,
            sid,
            last_state,
            _created_at,
        ) = row
        state = "offline" if sid is None else last_state
        return {
            "id": dev_id,
            "mac": dev_id,
            "name": name if name is not None else dev_id,
            "notes": notes or "",
            "room": room or "",
            "state": state,
            "lastSeen": last_seen,
            "sessionId": sid,
        }

    async def update_device(
        self,
        device_id: str,
        name: str | None = None,
        notes: str | None = None,
        room: str | None = None,
    ) -> bool:
        """V2 #6: partial update of friendly metadata.

        Only fields that are explicitly provided (non-None) are
        written. Empty string is treated as 'clear the field' (we
        store '' so list_devices() can distinguish 'unset' from
        'explicitly blank' — currently both are normalized to ''
        in the response, but the DB preserves the distinction for
        future use).

        Returns True if a row was updated, False if the device_id
        doesn't exist.
        """
        assert self._conn is not None
        # Build dynamic SET clause — only touch columns the caller
        # actually passed in. This keeps PATCH calls idempotent
        # and avoids trampling existing values when the client
        # sends a partial body (web only edits one field at a time).
        sets: list[str] = []
        args: list[Any] = []
        if name is not None:
            sets.append("name = ?")
            args.append(name)
        if notes is not None:
            sets.append("notes = ?")
            args.append(notes)
        if room is not None:
            sets.append("room = ?")
            args.append(room)
        if not sets:
            # No-op PATCH (e.g. client sent {}). Match HTTP PATCH
            # semantics: 200 with the unchanged record (we report
            # 'did it exist' as the return value; route layer
            # maps False → 404).
            async with self._conn.execute(
                "SELECT 1 FROM devices WHERE device_id = ?", (device_id,)
            ) as cur:
                row = await cur.fetchone()
            return row is not None
        args.append(device_id)
        cur = await self._conn.execute(
            f"UPDATE devices SET {', '.join(sets)} WHERE device_id = ?",
            args,
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def delete_device(self, device_id: str) -> bool:
        """V2 #6: remove a device and cascade its conversations /
        sessions to NULL (per the FK ON DELETE SET NULL clauses
        in the SCHEMA).

        Returns True if a device row was deleted, False if the
        device_id didn't exist (route layer maps False → 404).
        """
        assert self._conn is not None
        # PRAGMA foreign_keys=ON is set in connect() so the
        # ON DELETE SET NULL clauses actually fire. Without it,
        # SQLite parses the FK clauses but doesn't enforce them.
        cur = await self._conn.execute(
            "DELETE FROM devices WHERE device_id = ?", (device_id,)
        )
        await self._conn.commit()
        return cur.rowcount > 0

    # --- sessions ---

    async def open_session(self, session_id: str, device_id: str | None) -> None:
        assert self._conn is not None
        now = time.time()
        # V2 #4: always upsert, even when device_id is None — the
        # "unknown" bucket in upsert_device catches sessions opened
        # without a Device-Id header so they show up in /api/devices.
        await self.upsert_device(device_id)
        await self._conn.execute(
            "INSERT OR REPLACE INTO sessions(session_id, device_id, created_at, last_state) "
            "VALUES(?, ?, ?, 'idle')",
            (session_id, device_id, now),
        )
        await self._conn.commit()

    async def close_session(self, session_id: str) -> None:
        assert self._conn is not None
        now = time.time()
        await self._conn.execute(
            "UPDATE sessions SET closed_at = ? WHERE session_id = ? AND closed_at IS NULL",
            (now, session_id),
        )
        await self._conn.commit()

    async def update_session_state(self, session_id: str, state: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE sessions SET last_state = ? WHERE session_id = ?",
            (state, session_id),
        )
        await self._conn.commit()

    # --- conversations ---

    async def record_conversation(
        self,
        device_id: str | None,
        session_id: str | None,
        stt_text: str,
        assistant_text: str,
        llm_status: str = "ok",
    ) -> int:
        # V2 #4: same unknown-bucket rule as upsert_device — if the
        # firmware forgot the Device-Id header, the conversation row
        # should still be findable via /api/devices/unknown/conversations
        # (the synthetic bucket id), not lost under device_id=NULL.
        effective_device_id = device_id or "unknown"
        assert self._conn is not None
        now = time.time()
        async with self._conn.execute(
            "INSERT INTO conversations(device_id, session_id, started_at, ended_at, "
            "stt_text, assistant_text, llm_status) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (effective_device_id, session_id, now, now, stt_text, assistant_text, llm_status),
        ) as cur:
            cid = cur.lastrowid
        await self._conn.commit()
        assert cid is not None
        return cid

    async def list_conversations(
        self, device_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        assert self._conn is not None
        if device_id:
            sql = "SELECT id, device_id, session_id, started_at, ended_at, stt_text, assistant_text, llm_status FROM conversations WHERE device_id = ? ORDER BY started_at DESC LIMIT ?"
            args: tuple = (device_id, limit)
        else:
            sql = "SELECT id, device_id, session_id, started_at, ended_at, stt_text, assistant_text, llm_status FROM conversations ORDER BY started_at DESC LIMIT ?"
            args = (limit,)
        async with self._conn.execute(sql, args) as cur:
            rows = await cur.fetchall()
        out = []
        for cid, did, sid, started_at, ended_at, stt, ast, status in rows:
            turns: list[dict] = []
            if stt:
                turns.append(
                    {
                        "role": "user",
                        "text": stt,
                        "timestamp": started_at,
                    }
                )
            if ast:
                turns.append(
                    {
                        "role": "assistant",
                        "text": ast,
                        "timestamp": ended_at or started_at,
                    }
                )
            out.append(
                {
                    "id": str(cid),
                    "deviceId": did or "",
                    "sessionId": sid or "",
                    "startedAt": started_at,
                    "endedAt": ended_at,
                    "turns": turns,
                    "llmStatus": status,
                }
            )
        return out

    async def get_conversation(self, conversation_id: int) -> dict | None:
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT id, device_id, session_id, started_at, ended_at, stt_text, assistant_text, llm_status "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        cid, did, sid, started_at, ended_at, stt, ast, status = row
        turns: list[dict] = []
        if stt:
            turns.append({"role": "user", "text": stt, "timestamp": started_at})
        if ast:
            turns.append(
                {
                    "role": "assistant",
                    "text": ast,
                    "timestamp": ended_at or started_at,
                }
            )
        return {
            "id": str(cid),
            "deviceId": did or "",
            "sessionId": sid or "",
            "startedAt": started_at,
            "endedAt": ended_at,
            "turns": turns,
            "llmStatus": status,
        }

    # --- IoT ---

    async def list_iot_devices(self) -> list[dict]:
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT id, name, type, room, online, state_json FROM iot_devices ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        out = []
        for did, name, dtype, room, online, state_json in rows:
            out.append(
                {
                    "id": did,
                    "name": name,
                    "type": dtype,
                    "room": room,
                    "online": bool(online),
                    "state": json.loads(state_json),
                }
            )
        return out

    async def update_iot_state(self, device_id: str, state: dict) -> bool:
        assert self._conn is not None
        async with self._conn.execute(
            "UPDATE iot_devices SET state_json = ? WHERE id = ?",
            (json.dumps(state), device_id),
        ) as cur:
            changed = cur.rowcount > 0
        await self._conn.commit()
        return changed

    # --- config ---

    async def get_config(self) -> dict:
        assert self._conn is not None
        async with self._conn.execute("SELECT key, value_json FROM config_kv") as cur:
            rows = await cur.fetchall()
        return {k: json.loads(v) for k, v in rows}

    async def set_config(self, key: str, value: Any) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO config_kv(key, value_json, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value), time.time()),
        )
        await self._conn.commit()

    # --- raw (for logs streaming) ---

    @asynccontextmanager
    async def raw(self) -> AsyncIterator[aiosqlite.Connection]:
        assert self._conn is not None
        yield self._conn


# --- Module-level singleton (FastAPI dependency) ---

_db: BridgeDB | None = None


def get_db() -> BridgeDB:
    """Return the module-level BridgeDB singleton.

    FastAPI route handlers take this as a Depends() so the same
    connection is reused across requests (avoids the open/close
    per-request penalty).
    """
    global _db
    if _db is None:
        _db = BridgeDB()
    return _db


async def reset_db_for_tests() -> None:
    """Drop the singleton (test fixtures use this between cases)."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
