#!/usr/bin/env python3
"""End-to-end smoke test against a running xiaozhi-bridge instance.

Purpose
-------
Validate the *real* WebSocket → bridge → openclaw → sqlite path,
not the in-process mock path that pytest exercises. The hidden
class of bugs this catches is "library version drift" — e.g. V2 #4
discovered that ``ws.handshake`` became a method (not a property)
in websockets 16+, so device_id silently fell to None. The in-
process test never caught it because the test client's version
matched the test server's version.

What it does
------------
For each (label, device_id) pair in the CASE table, the script:

  1. Opens a WebSocket to bridge (optionally sending Device-Id).
  2. Sends the xiaozhi-esp32 hello message.
  3. Sends a listen.start frame, then 0.5s of silence PCM, then
     listen.stop. The mock ASR is configured to return a fixed
     text on listen.stop (see bridge/src/xiaozhi_bridge/asr/mock.py)
     — the actual STT is a V1 placeholder.
  4. Receives frames, skipping binary (Opus TTS) frames. Reads
     JSON until tts.state=stop arrives.
  5. Closes the connection with code 1000 *after* tts.stop — this
     is the critical part: closing before tts.stop would make
     server's _send_tts raise ConnectionClosedOK, which aborts
     _process_text *before* record_conversation runs.
  6. Asserts: (a) tts.stop received, (b) a conversation row
     appears in the live sqlite for this session_id.

Usage
-----
    # Default: run against the live VPS bridge (jarvis.beallen.top)
    python scripts/e2e_smoke.py

    # Run against a local bridge
    XIAOZHI_BRIDGE_WS_URL=ws://127.0.0.1:8000/xiaozhi/v1/ \\
    XIAOZHI_BRIDGE_DB=/root/projects/xiaozhi-bridge/bridge-data/_data/bridge.db \\
      python scripts/e2e_smoke.py

    # Run a single case
    python scripts/e2e_smoke.py --case esp32-001

Why this isn't in tests/
------------------------
  - Requires a real running bridge + openclaw + sqlite. CI doesn't
    have any of those.
  - The point is to *catch* things unit tests miss; running it
    in CI would just re-run the same library version the rest of
    the pipeline uses.
  - It's a manual / on-demand tool. Operator runs it after a
    rebuild before saying "live is good".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

try:
    import websockets
except ImportError:
    print("error: pip install websockets to use this script", file=sys.stderr)
    raise SystemExit(2)


# --- config (env-driven so the same script works on VPS / local) ---

DEFAULT_WS_URL = "wss://jarvis.beallen.top/xiaozhi/v1/"
# The bridge writes to a docker named volume on the VPS host:
#   xiaozhi-bridge_bridge-data → /app/data/bridge.db (in container)
# which Docker mounts at /var/lib/docker/volumes/... on the host.
# If you run this script from inside a container, set
# XIAOZHI_BRIDGE_DB=/app/data/bridge.db to read the in-container db.
DEFAULT_DB_PATH = "/var/lib/docker/volumes/xiaozhi-bridge_bridge-data/_data/bridge.db"

WS_URL = os.environ.get("XIAOZHI_BRIDGE_WS_URL", DEFAULT_WS_URL)
DB_PATH = os.environ.get("XIAOZHI_BRIDGE_DB", DEFAULT_DB_PATH)
SEND_TIMEOUT_S = 30.0  # max time waiting for tts.stop
SILENCE_BYTES = b"\x00\x00" * 100  # 0.3s of 16kHz mono PCM silence


@dataclass
class Case:
    label: str  # human-readable, used in logs/asserts
    device_id: str | None  # None → header omitted, goes to "unknown" bucket


# Default smoke battery: covers the two device shapes the V2 #4
# contract distinguishes (named vs unknown). Add more here as the
# surface area grows.
DEFAULT_CASES: tuple[Case, ...] = (
    Case(label="esp32-001-q1", device_id="esp32-001"),
    Case(label="esp32-001-q2", device_id="esp32-001"),
    Case(label="esp32-002-q1", device_id="esp32-002"),
    Case(label="unknown-q1", device_id=None),
    Case(label="unknown-q2", device_id=None),
)


# --- low-level db read (read-only, no aiosqlite needed) ---


def get_conversation_by_session(db_path: str, session_id: str) -> dict | None:
    """Return the conversation row for this session, or None."""
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT id, device_id, stt_text, assistant_text, llm_status "
            "FROM conversations WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "device_id": row[1],
        "stt_text": row[2],
        "assistant_text": row[3],
        "llm_status": row[4],
    }


# --- single e2e turn ---


async def run_turn(case: Case, *, verbose: bool = False) -> dict:
    """Run one hello → listen → tts.stop round and return a result dict.

    Returns:
        {
          "label": str,
          "device_id": str | None,
          "session_id": str | None,
          "stt_text": str | None,        # last stt frame text seen
          "tts_text": str | None,        # last tts frame text seen
          "tts_stop_seen": bool,
          "error": str | None,           # set on any non-graceful failure
          "db_row": dict | None,         # conversation row from sqlite
        }
    """
    headers: list[tuple[str, str]] = []
    if case.device_id is not None:
        headers.append(("Device-Id", case.device_id))

    result: dict = {
        "label": case.label,
        "device_id": case.device_id,
        "session_id": None,
        "stt_text": None,
        "tts_text": None,
        "tts_stop_seen": False,
        "error": None,
        "db_row": None,
    }

    try:
        async with websockets.connect(WS_URL, additional_headers=headers) as ws:
            # 1) hello
            await ws.send(json.dumps({
                "type": "hello", "version": 1,
                "features": {"mcp": True},
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }))
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            sid = hello["session_id"]
            result["session_id"] = sid
            if verbose:
                print(f"  [{case.label}] session_id={sid}")

            # 2) listen start → 0.3s silence → stop
            await ws.send(json.dumps({
                "session_id": sid, "type": "listen",
                "state": "start", "mode": "auto",
            }))
            await ws.send(SILENCE_BYTES)
            await asyncio.sleep(0.3)
            await ws.send(json.dumps({
                "session_id": sid, "type": "listen", "state": "stop",
            }))

            # 3) receive frames until tts.stop or timeout
            # The total deadline is SEND_TIMEOUT_S (30s) because openclaw
            # streaming can have 5-10s gaps between chunks when the LLM
            # is in "thinking" mode. The per-recv timeout is smaller
            # (RECV_GAP_S) but we re-check the overall deadline on each
            # iter so a slow stream doesn't kill us too early.
            deadline = time.monotonic() + SEND_TIMEOUT_S
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                recv_timeout = min(2.0, max(0.1, remaining))
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                except asyncio.TimeoutError:
                    continue
                # Binary frames are Opus TTS audio. Skip.
                if isinstance(raw, bytes):
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = obj.get("type")
                if kind == "stt":
                    result["stt_text"] = obj.get("text", "")
                    if verbose:
                        print(f"  [{case.label}] stt={result['stt_text']!r}")
                elif kind == "tts":
                    state = obj.get("state")
                    text = obj.get("text", "")
                    if state == "stop":
                        result["tts_stop_seen"] = True
                        if verbose:
                            print(f"  [{case.label}] tts.stop ✓")
                        break
                    elif text:
                        result["tts_text"] = text
                        if verbose:
                            print(f"  [{case.label}] tts text={text[:50]!r}")
                # ignore llm frames etc.

            # 4) After tts.stop, close gracefully. Server's _send_tts
            #    has already returned by this point so _process_text
            #    will reach record_conversation and write to sqlite.
            if result["tts_stop_seen"]:
                await ws.close(code=1000, reason="smoke-test done")
                # Wait up to 5s for the server's record_conversation
                # to commit. Poll the db instead of sleeping blindly —
                # a slow openclaw turn (tool calls, etc.) can take
                # several seconds to flush to sqlite.
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    if get_conversation_by_session(DB_PATH, result["session_id"]) is not None:
                        break
            else:
                result["error"] = "tts.stop not received within timeout"

    except websockets.exceptions.WebSocketException as e:
        result["error"] = f"ws error: {e!r}"
    except Exception as e:  # noqa: BLE001
        result["error"] = f"unexpected: {e!r}"

    # 5) Check the sqlite row landed.
    if result["session_id"] is not None:
        result["db_row"] = get_conversation_by_session(DB_PATH, result["session_id"])
    return result


# --- runner ---


async def run_cases(cases: Sequence[Case], *, verbose: bool = False) -> list[dict]:
    results: list[dict] = []
    for c in cases:
        if verbose:
            print(f"\n→ case: {c.label} (device_id={c.device_id!r})")
        r = await run_turn(c, verbose=verbose)
        results.append(r)
    return results


def format_report(results: list[dict]) -> str:
    lines: list[str] = []
    lines.append(f"{'label':24s} {'device_id':12s} {'sid':28s} {'stt':8s} {'tts.stop':8s} {'db':6s} err")
    for r in results:
        sid = (r["session_id"] or "-")[:26]
        stt = "✓" if r["stt_text"] else "✗"
        stop = "✓" if r["tts_stop_seen"] else "✗"
        db = "✓" if r["db_row"] is not None else "✗"
        err = r["error"] or ""
        lines.append(
            f"{r['label']:24s} {str(r['device_id']):12s} {sid:28s} {stt:8s} {stop:8s} {db:6s} {err}"
        )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--case", action="append",
        help="Only run cases whose label starts with this prefix. Repeatable.",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print per-frame detail.",
    )
    args = p.parse_args()

    cases = DEFAULT_CASES
    if args.case:
        wanted = list(args.case)
        cases = tuple(c for c in DEFAULT_CASES if any(c.label.startswith(w) for w in wanted))
        if not cases:
            print(f"no cases matched prefixes: {wanted}", file=sys.stderr)
            return 2

    print(f"bridge: {WS_URL}")
    print(f"db:     {DB_PATH}")
    print(f"cases:  {len(cases)}\n")

    results = asyncio.run(run_cases(cases, verbose=args.verbose))
    print()
    print(format_report(results))

    # exit code: 0 if every case has tts.stop AND a db row, else 1
    n_ok = sum(1 for r in results if r["tts_stop_seen"] and r["db_row"] is not None)
    n_total = len(results)
    print(f"\n{n_ok}/{n_total} cases landed a conversation row in sqlite")
    return 0 if n_ok == n_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
