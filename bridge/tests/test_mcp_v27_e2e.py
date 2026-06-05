"""End-to-end V2 #7 tests: full _process_text loop with mock esp32.

These tests exercise the actual V2 #7 code path:
  1. LLM stream emits a TOOL_CALL event
  2. _process_text builds the JSON-RPC payload and calls _send_mcp_call
  3. The mock esp32 "responds" by resolving the pending future
  4. _process_text re-issues chat_stream with the augmented messages
  5. The final assistant text gets sent to TTS

We stub the LLM (openclaw) with a fake that returns deterministic
chunks, and stub the WebSocket (since the real _process_text writes
to the device over a WS).
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from xiaozhi_bridge.llm.base import LLMEvent, Message
from xiaozhi_bridge.mcp.tools import (
    DeviceToolHandler,
    clear_tools,
    register_tool,
)
from xiaozhi_bridge.protocol.states import SessionContext, SessionState

# --- Helpers ---


def make_message(role: str, **kwargs) -> Message:
    return Message(role=role, **kwargs)


class FakeLLM:
    """A fake LLM that returns a configurable sequence of LLMEvent streams.

    The first call to chat_stream returns events_for_call[0], the second
    returns events_for_call[1], and so on.
    """

    def __init__(self, events_per_call: list[list[LLMEvent]]):
        self._events_per_call = events_per_call
        self._call_index = 0
        self.call_log: list[list[Message]] = []

    async def chat_stream(self, messages, tools=None, system=None):
        self.call_log.append(list(messages))
        idx = min(self._call_index, len(self._events_per_call) - 1)
        self._call_index += 1
        for event in self._events_per_call[idx]:
            yield event


# --- V2 #7.7: full _process_text with set_volume tool call ---


@pytest.mark.asyncio
async def test_process_text_dispatches_set_volume_to_esp32(monkeypatch):
    """V2 #7 end-to-end: user says 'set volume to 50' →
    LLM emits tool_call for set_volume →
    bridge forwards JSON-RPC to esp32 →
    esp32 responds 'ok' →
    LLM says '音量已设为 50' →
    TTS sends that text.

    We mock the LLM, the WebSocket, and the esp32 response so the
    test runs end-to-end without external services.
    """
    # Reset tool registry for clean state.
    clear_tools()
    try:
        # --- Arrange: a FakeLLM that returns tool_call then text ---
        fake_llm = FakeLLM(events_per_call=[
            # Call 1: emit tool_call for set_volume
            [LLMEvent(kind="tool_call", tool_call={
                "id": "call_xyz",
                "name": "set_volume",
                "arguments": {"volume": 50},
            })],
            # Call 2: emit final text (after seeing the tool result)
            [LLMEvent(kind="text", text="音量"), LLMEvent(kind="text", text="已调到 50"),
             LLMEvent(kind="done")],
        ])

        # Build a real bridge server. We won't start it (no asyncio
        # server loop); we call _process_text directly with a mock ws.
        from xiaozhi_bridge.server import XiaozhiBridgeServer

        # No AppConfig needed; we use __new__ to bypass __init__.
        server = XiaozhiBridgeServer.__new__(XiaozhiBridgeServer)
        # Bypass __init__; manually set the minimum the methods need.
        server.llm = fake_llm
        server.log = MagicMock()
        server.sessions = {}
        server._codecs = {}
        server._wake_grace_tasks = []
        server.vad = None
        server._db = None
        server.asr = MagicMock()
        server.tts = MagicMock()
        # TTS is called in _send_tts; we replace it with a noop
        async def fake_send_tts(ws, session, text):
            server._last_tts_text = text
        server._send_tts = fake_send_tts
        # Transition is noop
        async def fake_transition(session, state):
            session.transition(state)
        server._transition = fake_transition

        # --- Register a DeviceToolHandler that simulates esp32 ---
        # We need to capture the future and resolve it as if esp32 replied.
        async def send_mcp_call(tool_name, arguments, future):
            server._esp32_request = {"tool": tool_name, "arguments": arguments}
            # Simulate esp32 responding after 1 tick.
            asyncio.get_event_loop().call_soon(
                future.set_result,
                {"content": [{"type": "text", "text": "ok"}]},
            )

        register_tool(DeviceToolHandler(
            name="set_volume",
            description="Set volume",
            input_schema={"type": "object", "properties": {"volume": {"type": "integer"}}},
            send_mcp_call=send_mcp_call,
        ))

        # Build a mock session.
        session = SessionContext(
            session_id="test-e2e-sess",
            device_id="test-device",
        )
        # Build a mock ws that records all sent messages.
        sent: list[str] = []
        class MockWS:
            async def send(self, msg):
                sent.append(msg)
            # async iterator yields no incoming messages
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration
        ws = MockWS()

        # --- Act: run _process_text ---
        await server._process_text(ws, session, "把音量调到 50")

        # --- Assert ---
        # 1. LLM was called twice (first time before tool, second after)
        assert len(fake_llm.call_log) == 2, f"LLM should be called twice, got {len(fake_llm.call_log)}"
        # 2. Second call's messages include the tool result
        second_call_msgs = fake_llm.call_log[1]
        tool_msgs = [m for m in second_call_msgs if m.role == "tool"]
        assert len(tool_msgs) == 1, f"expected 1 tool result, got {len(tool_msgs)}"
        assert tool_msgs[0].tool_call_id == "call_xyz"
        # 3. Device received the right tool call
        assert server._esp32_request == {"tool": "self.audio_speaker.set_volume", "arguments": {"volume": 50}}
        # 4. Final TTS text is the LLM's final text
        assert server._last_tts_text == "音量已调到 50"
        # 5. Session reached IDLE
        assert session.state == SessionState.IDLE
    finally:
        clear_tools()


@pytest.mark.asyncio
async def test_process_text_no_tool_call_just_text(monkeypatch):
    """V2 #7: LLM that doesn't call any tool should still produce text."""
    fake_llm = FakeLLM(events_per_call=[
        [LLMEvent(kind="text", text="你好"), LLMEvent(kind="text", text="啊"),
         LLMEvent(kind="done")],
    ])

    from xiaozhi_bridge.server import XiaozhiBridgeServer
    # No AppConfig needed; we use __new__ to bypass __init__.
    server = XiaozhiBridgeServer.__new__(XiaozhiBridgeServer)
    server.llm = fake_llm
    server.log = MagicMock()
    server.sessions = {}
    server._codecs = {}
    server._wake_grace_tasks = []
    server.vad = None
    server._db = None
    server.asr = MagicMock()
    server.tts = MagicMock()
    async def fake_send_tts(ws, session, text):
        server._last_tts_text = text
    server._send_tts = fake_send_tts
    async def fake_transition(session, state):
        session.transition(state)
    server._transition = fake_transition

    session = SessionContext(session_id="t1", device_id="d1")
    class MockWS:
        async def send(self, msg):
            pass
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration
    ws = MockWS()

    await server._process_text(ws, session, "你好")
    assert server._last_tts_text == "你好啊"
    assert len(fake_llm.call_log) == 1


@pytest.mark.asyncio
async def test_process_text_tool_timeout_falls_back_to_text(monkeypatch):
    """V2 #7: if the device times out, the LLM gets a timeout error as
    the tool result, and can either retry or fall back to text."""
    fake_llm = FakeLLM(events_per_call=[
        # Call 1: try set_volume
        [LLMEvent(kind="tool_call", tool_call={
            "id": "call_timeout",
            "name": "set_volume",
            "arguments": {"volume": 30},
        })],
        # Call 2: after seeing the timeout, give up and just say text
        [LLMEvent(kind="text", text="设备没响应"), LLMEvent(kind="done")],
    ])

    from xiaozhi_bridge.server import XiaozhiBridgeServer
    # No AppConfig needed; we use __new__ to bypass __init__.
    server = XiaozhiBridgeServer.__new__(XiaozhiBridgeServer)
    server.llm = fake_llm
    server.log = MagicMock()
    server.sessions = {}
    server._codecs = {}
    server._wake_grace_tasks = []
    server.vad = None
    server._db = None
    server.asr = MagicMock()
    server.tts = MagicMock()
    async def fake_send_tts(ws, session, text):
        server._last_tts_text = text
    server._send_tts = fake_send_tts
    async def fake_transition(session, state):
        session.transition(state)
    server._transition = fake_transition

    # Register a device handler that never responds.
    async def send_mcp_call_no_respond(tool_name, arguments, future):
        pass  # never set future
    register_tool(DeviceToolHandler(
        name="set_volume",
        description="Set volume",
        input_schema={"type": "object", "properties": {"volume": {"type": "integer"}}},
        send_mcp_call=send_mcp_call_no_respond,
        timeout=0.05,  # very short timeout for test
    ))

    session = SessionContext(session_id="t2", device_id="d2")
    class MockWS:
        async def send(self, msg):
            pass
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration
    ws = MockWS()

    await server._process_text(ws, session, "调音量到 30")
    # After timeout, the LLM gets an error string as the tool result
    # and should fall back to text.
    assert server._last_tts_text == "设备没响应"
    # Second call's tool message has an error in its content
    second_call_msgs = fake_llm.call_log[1]
    tool_msgs = [m for m in second_call_msgs if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "Error" in tool_msgs[0].content or "timed out" in tool_msgs[0].content
    clear_tools()
