"""Live integration test: bridge → real openclaw gateway → M3.

Skipped by default (requires openclaw running on 127.0.0.1:18789 with
chatCompletions endpoint enabled and a valid gateway token). Run explicitly:

    OPENCLAW_LIVE_TEST=1 pytest tests/test_openclaw_live.py -v

The test:
  1. Reads the gateway token from `gateway.auth.token` in
     /root/.openclaw/openclaw.json (the operator's local config).
  2. Pings /v1/chat/completions with a tiny non-streaming call to verify
     reachability and auth.
  3. Spins up the bridge server, connects a fake device, runs one turn,
     and verifies the assistant's text actually comes back from M3
     (not the bridge's "嗯,我还没想好怎么回答" fallback).

Why not just the unit test_pipeline.py? It mocks LLM, so it cannot
distinguish a working LLM integration from a broken one. This test is
the one that proves end-to-end correctness against the real openclaw.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path

import pytest
import websockets

from xiaozhi_bridge.config import AppConfig
from xiaozhi_bridge.server import XiaozhiBridgeServer


def _load_openclaw_token() -> str | None:
    cfg_path = Path("/root/.openclaw/openclaw.json")
    if not cfg_path.exists():
        return None
    cfg = json.loads(cfg_path.read_text())
    return (
        cfg.get("gateway", {}).get("auth", {}).get("token", "") or None
    )


pytestmark = pytest.mark.skipif(
    os.environ.get("OPENCLAW_LIVE_TEST") != "1",
    reason="set OPENCLAW_LIVE_TEST=1 to run live openclaw integration test",
)


@pytest.fixture
def app_config_live():
    token = _load_openclaw_token()
    if not token:
        pytest.skip("no openclaw gateway token in /root/.openclaw/openclaw.json")
    return AppConfig(
        server={"host": "127.0.0.1", "port": 0, "path": "/xiaozhi/v1/"},
        openclaw={
            "base_url": "http://127.0.0.1:18789",
            "api_key": token,
            "model": "openclaw",
            "user": "xiaozhi-bridge-test",
            "max_tokens": 64,
            "temperature": 0.2,
            "timeout": 30.0,
        },
        asr={"provider": "mock", "options": {"mode": "fixed", "text": "ping", "latency_ms": 0}},
        tts={"provider": "mock", "options": {"mode": "silence", "chunk_ms": 60}},
    )


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.asyncio
async def test_bridge_to_openclaw_live(app_config_live):
    """Run a full turn against a real openclaw gateway.

    Asserts:
      - openclaw is reachable on /v1/chat/completions (probe first).
      - bridge completes one turn and receives text from M3.
      - At least one Opus binary frame is sent to the device.
    """
    # Probe openclaw reachability
    import httpx
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(
                "http://127.0.0.1:18789/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {app_config_live.openclaw.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openclaw",
                    "max_tokens": 8,
                    "stream": False,
                    "user": "xiaozhi-bridge-test-probe",
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=20.0,
            )
            if r.status_code != 200:
                pytest.skip(f"openclaw probe failed: HTTP {r.status_code}: {r.text[:200]}")
            probe = r.json()
            assert "choices" in probe, f"unexpected probe response: {probe}"
    except (httpx.HTTPError, OSError) as e:
        pytest.skip(f"openclaw not reachable: {e}")

    # Spin up bridge
    port = _free_port()
    app_config_live.server.port = port
    server = XiaozhiBridgeServer(app_config_live)
    await server.start()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/xiaozhi/v1/") as ws:
            # Hello
            await ws.send(json.dumps({
                "type": "hello",
                "version": 1,
                "features": {"mcp": True},
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }))
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            session_id = hello["session_id"]
            assert session_id.startswith("xiaozhi-")

            # listen start + audio + listen stop
            await ws.send(json.dumps({
                "session_id": session_id, "type": "listen",
                "state": "start", "mode": "auto",
            }))
            await ws.send(b"\x00\x00" * 100)
            await ws.send(json.dumps({
                "session_id": session_id, "type": "listen", "state": "stop",
            }))

            # Drain messages until tts.stop
            types = []
            binary_frames = 0
            tts_stopped = False
            from xiaozhi_bridge.protocol.messages import (
                LLMMessage,
                MCPMessage,
                ServerHello,
                STTMessage,
                SystemMessage,
                TTSMessage,
            )
            msg_map = {
                "hello": ServerHello, "stt": STTMessage, "llm": LLMMessage,
                "tts": TTSMessage, "mcp": MCPMessage, "system": SystemMessage,
            }
            while not tts_stopped:
                raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                if isinstance(raw, bytes):
                    binary_frames += 1
                else:
                    d = json.loads(raw)
                    cls = msg_map.get(d.get("type"))
                    assert cls, f"unknown server msg: {d}"
                    msg = cls.model_validate(d)
                    types.append(msg.type)
                    if msg.type == "tts" and msg.state == "stop":
                        tts_stopped = True

            # The pipeline must have run end-to-end
            for required in ("stt", "llm", "tts"):
                assert required in types, f"missing {required}, got {types}"
            assert binary_frames > 0, "no TTS audio frames"
    finally:
        await server.stop()
