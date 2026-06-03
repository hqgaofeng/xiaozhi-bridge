"""End-to-end pipeline test for xiaozhi-bridge.

Verifies the full hello → listen start/stop → ASR (mock) → LLM (mocked openclaw)
→ TTS (mock) → opus frames flow, all over a real WebSocket connection.

The LLM is mocked (we don't talk to real openclaw) — we monkey-patch
OpenClawLLM.chat_stream to return canned text events.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from xiaozhi_bridge.config import AppConfig
from xiaozhi_bridge.llm.base import LLMEvent
from xiaozhi_bridge.server import XiaozhiBridgeServer

# --- Fake openclaw LLM ---


class FakeOpenClaw:
    """A fake OpenClawLLM that yields canned events without HTTP."""

    def __init__(self, *args, **kwargs):
        pass

    async def chat_stream(self, messages, tools=None, system=None):
        yield LLMEvent(kind="text", text="你好")
        yield LLMEvent(kind="text", text="世界")
        yield LLMEvent(kind="done", finish_reason="end_turn")

    async def close(self):
        pass


# --- Fixtures ---


@pytest.fixture
def app_config():
    return AppConfig(
        server={"host": "127.0.0.1", "port": 0, "path": "/xiaozhi/v1/"},
        asr={"provider": "mock", "options": {"mode": "fixed", "text": "测试", "latency_ms": 0}},
        tts={"provider": "mock", "options": {"mode": "silence", "chunk_ms": 60}},
    )


# --- The actual end-to-end test ---


@pytest.mark.asyncio
async def test_full_turn_pipeline(monkeypatch, app_config):
    """Run server, connect a fake device, run one turn, verify frames."""
    # Patch the LLM factory. `get_llm` looks up the registry dict; we
    # replace the openclaw entry with a callable returning our fake.
    from xiaozhi_bridge.llm.base import _REGISTRY
    monkeypatch.setitem(_REGISTRY, "openclaw", FakeOpenClaw)

    server = XiaozhiBridgeServer(app_config)
    # Pick a free port
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app_config.server.port = port

    await server.start()
    try:
        url = f"ws://127.0.0.1:{port}/xiaozhi/v1/"
        async with websockets.connect(url) as ws:
            # 1) hello handshake
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
            server_hello_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            # Server response is ServerHello (not HelloMessage). Parse it
            # by round-tripping through Pydantic so we keep the same
            # shape as parse_client_message would for the inverse.
            from xiaozhi_bridge.protocol.messages import ServerHello
            server_hello = ServerHello.model_validate_json(server_hello_raw)
            assert server_hello.type == "hello"
            assert server_hello.session_id.startswith("xiaozhi-")
            session_id = server_hello.session_id

            # 2) listen start
            await ws.send(json.dumps({
                "session_id": session_id,
                "type": "listen",
                "state": "start",
                "mode": "auto",
            }))

            # 2b) Send some "audio" (just bytes — server decodes via mock codec
            # which is PassThroughCodec, so it'll just buffer whatever we give).
            # We need non-empty buffer for _process_turn to do anything.
            await ws.send(b"\x00\x00" * 100)  # ~50 samples of silence

            # 3) listen stop → triggers pipeline
            await ws.send(json.dumps({
                "session_id": session_id,
                "type": "listen",
                "state": "stop",
            }))

            # 4) Collect all server messages until tts.stop
            messages = []
            binary_frames = []
            tts_stop_seen = False
            from xiaozhi_bridge.protocol.messages import (
                LLMMessage,
                MCPMessage,
                ServerHello,
                STTMessage,
                SystemMessage,
                TTSMessage,
            )
            server_types = {
                "hello": ServerHello,
                "stt": STTMessage,
                "llm": LLMMessage,
                "tts": TTSMessage,
                "mcp": MCPMessage,
                "system": SystemMessage,
            }
            while not tts_stop_seen:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                if isinstance(raw, bytes):
                    binary_frames.append(raw)
                else:
                    data = json.loads(raw)
                    cls = server_types.get(data.get("type"))
                    assert cls is not None, f"unknown server msg: {data}"
                    msg = cls.model_validate(data)
                    messages.append(msg)
                    if msg.type == "tts" and msg.state == "stop":
                        tts_stop_seen = True

            # Verify the expected message sequence
            types = [m.type for m in messages]
            assert "stt" in types, f"missing stt, got {types}"
            assert "llm" in types, f"missing llm, got {types}"
            assert "tts" in types, f"missing tts, got {types}"

            # STT should echo our mocked ASR text
            stt_msg = next(m for m in messages if m.type == "stt")
            assert stt_msg.text == "测试"

            # We expect at least one Opus binary frame in between
            assert len(binary_frames) > 0, "no TTS audio frames received"
    finally:
        await server.stop()
