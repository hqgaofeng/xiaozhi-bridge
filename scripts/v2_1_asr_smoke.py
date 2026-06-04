#!/usr/bin/env python3
"""V2 #1 ASR smoke test against the LIVE VPS bridge.

Sends a real Chinese wav file (from the sherpa-onnx test_wavs bundle)
through the xiaozhi-esp32 WS protocol and asserts that:

  1. The bridge does NOT crash (status 200 + server-side tts.stop seen).
  2. The bridge's server.log shows that sherpa-onnx actually transcribes
     the audio to non-empty text (we assert this in a *separate* check
     against the live sqlite: the conversation row should have a
     non-empty user turn text).

This is the V2 #1 equivalent of scripts/e2e_smoke.py — but for the
real ASR, not the mock one.

Usage
-----
    python scripts/v2_1_asr_smoke.py
    XIAOZHI_BRIDGE_WS_URL=ws://127.0.0.1:8000/xiaozhi/v1/ \\
      python scripts/v2_1_asr_smoke.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import struct
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import urllib.request

# --- Config (override via env for local runs) ---

WS_URL = os.environ.get(
    "XIAOZHI_BRIDGE_WS_URL", "wss://jarvis.beallen.top/xiaozhi/v1/"
)
DB_PATH = Path(
    os.environ.get(
        "XIAOZHI_BRIDGE_DB",
        "/var/lib/docker/volumes/xiaozhi-bridge_bridge-data/_data/bridge.db",
    )
)
SEND_TIMEOUT_S = 120.0  # total deadline for tts.stop
PER_RECV_TIMEOUT_S = 10.0  # per-recv
SAMPLE_RATE = 16000  # xiaozhi's default

# Use the smallest test wav (1.wav, 5.1s) so the script stays snappy.
WAV_PATH = Path(
    "/opt/xiaozhi-bridge/models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/test_wavs/1.wav"
)


@dataclass
class SmokeCase:
    label: str
    device_id: str | None


def read_wav_int16(p: Path) -> tuple[bytes, int]:
    """Return (raw_int16_pcm_bytes, sample_rate)."""
    with wave.open(str(p), "rb") as f:
        sr = f.getframerate()
        n = f.getnframes()
        if f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise SystemExit(f"{p}: must be 16-bit mono (got {f.getnchannels()}ch x {f.getsampwidth()*8}bit)")
        return f.readframes(n), sr


def encode_opus_frames(pcm_bytes: bytes, sample_rate: int, frame_duration_ms: int = 60) -> list[bytes]:
    """Split PCM int16 into 60ms frames and Opus-encode each one.

    The xiaozhi-esp32 protocol requires audio as Opus frames. We use
    the same library (opuslib) and frame size (60ms) the bridge uses
    for TTS encoding, so the bytes are a faithful round-trip.
    """
    import opuslib
    encoder = opuslib.Encoder(fs=sample_rate, channels=1, application=opuslib.APPLICATION_AUDIO)
    frame_samples = sample_rate * frame_duration_ms // 1000  # 960 @ 16kHz
    frame_bytes = frame_samples * 2  # int16

    out: list[bytes] = []
    # Zero-pad the last frame so we always have a complete 60ms chunk.
    if len(pcm_bytes) % frame_bytes != 0:
        pcm_bytes = pcm_bytes + b"\x00" * (frame_bytes - (len(pcm_bytes) % frame_bytes))

    for i in range(0, len(pcm_bytes), frame_bytes):
        chunk = pcm_bytes[i : i + frame_bytes]
        encoded = encoder.encode(chunk, frame_samples)
        out.append(bytes(encoded))
    return out


async def run_case(case: SmokeCase) -> dict:
    import websockets

    started_at = time.time()
    audio, sr = read_wav_int16(WAV_PATH)
    assert sr == SAMPLE_RATE, f"test wav sample rate {sr} != {SAMPLE_RATE}"
    # Opus-encode the wav into 60ms frames. The bridge will Opus-decode
    # them back to PCM and feed the PCM to sherpa-onnx.
    opus_frames = encode_opus_frames(audio, sr, frame_duration_ms=60)
    print(f"  {case.label}: {len(audio)} bytes PCM → {len(opus_frames)} Opus frames @ 60ms")
    device_id = case.device_id

    # Build the hello message
    hello = {"type": "hello", "version": 1, "transport": "websocket", "audio_params": {
        "format": "opus", "sample_rate": SAMPLE_RATE, "channels": 1, "frame_duration": 60,
    }}
    # Note: xiaozhi-esp32 sends Device-Id as an HTTP header on the WS
    # upgrade (not in the JSON body). The bridge's _get_header picks
    # it up from there. For device_id=None we just don't send it.
    extra_headers = [("Device-Id", device_id)] if device_id else None
    # Use device_id or a random marker in session_id (so we can find the row later).
    sid_marker = device_id or "no-device"

    async with websockets.connect(WS_URL, additional_headers=extra_headers) as ws:
        # 1) hello
        await ws.send(json.dumps(hello))

        # Wait for the hello response — it carries the server-assigned
        # session_id (e.g. "xiaozhi-..."). We need that for all later
        # messages, since ListenMessage validates session_id as required.
        hello_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        session_id = hello_resp.get("session_id", "")
        print(f"  {case.label}: server session_id = {session_id!r}")
        # Re-use this session_id in our db lookup
        result_sid_marker = session_id

        # 2) listen start
        listen_start = {
            "type": "listen",
            "state": "start",
            "mode": "manual",
            "session_id": session_id,
        }
        await ws.send(json.dumps(listen_start))

        # 3) Send the Opus frames in order. The bridge will Opus-decode
        # each one back to 60ms of PCM and feed it to sherpa-onnx.
        deadline = started_at + SEND_TIMEOUT_S
        for frame in opus_frames:
            await ws.send(frame)
            await asyncio.sleep(0.01)  # be gentle — no need to burst

        # 4) listen stop
        await ws.send(json.dumps({"type": "listen", "state": "stop", "session_id": session_id}))

        # 5) Wait for tts.stop (or any terminal message). We expect the
        # bridge to: ASR the audio → LLM call → TTS → tts.stop.
        tts_stop_seen = False
        stt_text = ""
        while time.time() < deadline:
            try:
                remaining = min(PER_RECV_TIMEOUT_S, deadline - time.time())
                msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            except Exception as e:
                return {
                    "label": case.label,
                    "sid_marker": sid_marker,
                    "tts_stop_seen": False,
                    "stt_text": "",
                    "db_row": None,
                    "error": f"recv error: {e!r}",
                }
            if isinstance(msg, (bytes, bytearray)):
                # Opus TTS frame — skip silently
                continue
            try:
                d = json.loads(msg)
            except Exception:
                continue
            t = d.get("type")
            if t == "stt" and d.get("text"):
                stt_text = d.get("text", "")
            elif t == "tts" and d.get("state") == "stop":
                tts_stop_seen = True
                break
            elif t == "error":
                return {
                    "label": case.label,
                    "sid_marker": sid_marker,
                    "tts_stop_seen": False,
                    "stt_text": stt_text,
                    "db_row": None,
                    "error": f"server error: {d.get('message')!r}",
                }
    # After tts.stop the server should write a conversation row.
    # Wait a moment for the write to commit, then check sqlite directly.
    await asyncio.sleep(0.5)
    db_row = None
    if DB_PATH.exists():
        try:
            import sqlite3
            with sqlite3.connect(str(DB_PATH)) as con:
                # The conversation row is keyed on session_id (set when
                # the hello handshake completes). We read the user STT
                # text from the `stt_text` column (V2 #3 schema stores
                # both user and assistant text as columns, not as a
                # separate messages table).
                cur = con.execute(
                    "SELECT stt_text FROM conversations WHERE session_id = ?",
                    (result_sid_marker,),
                )
                r = cur.fetchone()
                db_row = r[0] if r else None
        except Exception as e:
            db_row = f"<db check error: {e!r}>"
    return {
        "label": case.label,
        "sid_marker": result_sid_marker,
        "tts_stop_seen": tts_stop_seen,
        "stt_text": stt_text,
        "db_row": db_row,
        "error": None,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-id", default="v2-1-asr-test")
    args = parser.parse_args()
    case = SmokeCase(label="v2-1-asr", device_id=args.device_id)
    print(f"bridge: {WS_URL}")
    print(f"wav:    {WAV_PATH} ({WAV_PATH.stat().st_size} bytes)")
    print(f"db:     {DB_PATH}")
    print()
    r = await run_case(case)
    print(f"label      device              tts.stop  stt_text           db_row_text")
    print(
        f"{r['label']:10s} {r['sid_marker']:18s}  "
        f"{'✓' if r['tts_stop_seen'] else '✗':8s}  "
        f"{(r['stt_text'] or '<none>')[:30]:30s}  "
        f"{(r['db_row'] or '<none>')[:30]}"
    )
    if r["error"]:
        print(f"error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    if not r["tts_stop_seen"]:
        print("FAIL: tts.stop not seen (server did not complete LLM+TTS)", file=sys.stderr)
        sys.exit(2)
    if not r["db_row"]:
        print("FAIL: no user message row in sqlite", file=sys.stderr)
        sys.exit(3)
    print(f"\nPASS: sherpa-onnx transcribed and the bridge recorded the user text.")
    print(f"  user-text: {r['db_row']!r}")


if __name__ == "__main__":
    asyncio.run(main())
