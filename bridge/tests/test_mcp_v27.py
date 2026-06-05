"""Tests for V2 #7 reverse MCP (bridge -> esp32 tool dispatch)."""

import asyncio

import pytest

from xiaozhi_bridge.mcp.tools import (
    DeviceToolHandler,
    call_tool,
    clear_tools,
    register_function,
    register_tool,
)
from xiaozhi_bridge.protocol.states import SessionContext


@pytest.fixture(autouse=True)
def reset_tools():
    """Reset tool registry between tests."""
    clear_tools()
    yield
    clear_tools()


# --- DeviceToolHandler basics ---


@pytest.mark.asyncio
async def test_device_tool_handler_dispatches_to_future():
    """V2 #7: DeviceToolHandler returns the future result to the LLM."""
    # Track what was "sent" (in production this becomes a JSON-RPC
    # message over WebSocket). We use a closure to capture.
    sent_calls: list[dict] = []

    async def send_mcp_call(tool_name, arguments, future):
        sent_calls.append({"name": tool_name, "arguments": arguments, "future": future})

    register_tool(DeviceToolHandler(
        name="self.audio_speaker.set_volume",
        description="Set volume",
        input_schema={
            "type": "object",
            "properties": {"volume": {"type": "integer"}},
        },
        send_mcp_call=send_mcp_call,
    ))

    # Manually invoke the tool; in production this happens inside
    # _process_text's tool-use loop.
    # Call the registered tool by name (the LLM-side entry point).
    # Inject the future into our send_mcp_call closure:
    captured: list = []

    async def send_mcp_call2(tool_name, arguments, fut):
        captured.append({"name": tool_name, "arguments": arguments, "future": fut})
        # Simulate the device replying:
        fut.set_result({"content": [{"type": "text", "text": "ok"}]})

    # Re-register with the resolving closure.
    clear_tools()
    register_tool(DeviceToolHandler(
        name="self.audio_speaker.set_volume",
        description="Set volume",
        input_schema={
            "type": "object",
            "properties": {"volume": {"type": "integer"}},
        },
        send_mcp_call=send_mcp_call2,
    ))
    result = await call_tool("self.audio_speaker.set_volume", {"volume": 50})
    assert captured[0]["name"] == "self.audio_speaker.set_volume"
    assert captured[0]["arguments"] == {"volume": 50}
    assert result == {"content": [{"type": "text", "text": "ok"}]}


@pytest.mark.asyncio
async def test_device_tool_handler_timeout():
    """V2 #7: timeout when device doesn't respond (5s default)."""
    async def send_mcp_call(tool_name, arguments, future):
        # Never set_result — simulate device offline.
        pass

    register_tool(DeviceToolHandler(
        name="self.audio_speaker.set_volume",
        description="Set volume",
        input_schema={"type": "object", "properties": {"volume": {"type": "integer"}}},
        send_mcp_call=send_mcp_call,
        timeout=0.1,  # fast timeout for test
    ))
    with pytest.raises(TimeoutError):
        await call_tool("self.audio_speaker.set_volume", {"volume": 50})


@pytest.mark.asyncio
async def test_device_tool_handler_is_error():
    """V2 #7: device returning isError=true surfaces as RuntimeError."""
    async def send_mcp_call(tool_name, arguments, future):
        future.set_result({
            "content": [{"type": "text", "text": "speaker fault"}],
            "isError": True,
        })

    register_tool(DeviceToolHandler(
        name="self.audio_speaker.set_volume",
        description="Set volume",
        input_schema={"type": "object", "properties": {"volume": {"type": "integer"}}},
        send_mcp_call=send_mcp_call,
    ))
    with pytest.raises(RuntimeError, match="speaker fault"):
        await call_tool("self.audio_speaker.set_volume", {"volume": 50})


@pytest.mark.asyncio
async def test_device_tool_handler_esp32_name_mapping():
    """V2 #7: ESP32_NAME_MAP translates bridge->esp32 tool names."""
    captured: list = []

    async def send_mcp_call(tool_name, arguments, future):
        captured.append({"name": tool_name, "arguments": arguments})
        future.set_result({"content": [{"type": "text", "text": "ok"}]})

    register_tool(DeviceToolHandler(
        name="self.audio_speaker.set_volume",
        description="Set volume",
        input_schema={"type": "object", "properties": {"volume": {"type": "integer"}}},
        send_mcp_call=send_mcp_call,
    ))
    await call_tool("self.audio_speaker.set_volume", {"volume": 75})
    assert captured[0]["name"] == "self.audio_speaker.set_volume"


# --- FunctionTool still works (V1 backward-compat) ---


@pytest.mark.asyncio
async def test_function_tool_still_works():
    """V2 #7: V1 FunctionTool continues to work for local tools."""

    @register_function(
        name="test.add",
        description="Add two numbers",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    )
    async def add(a: int, b: int) -> int:
        return a + b

    result = await call_tool("test.add", {"a": 2, "b": 3})
    assert result == 5


# --- SessionContext stores pending_mcp_calls ---


def test_session_context_has_pending_mcp_calls():
    """V2 #7: SessionContext exposes pending_mcp_calls dict."""
    ctx = SessionContext(session_id="test-sess")
    assert ctx.pending_mcp_calls == {}
    assert ctx.mcp_request_id == 0
    # Manually allocate a request id (mimicking _send_mcp_call).
    ctx.mcp_request_id += 1
    assert ctx.mcp_request_id == 1


def test_session_context_resolves_pending_call():
    """V2 #7: a future stored in pending_mcp_calls can be resolved."""
    ctx = SessionContext(session_id="test-sess")
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    ctx.pending_mcp_calls[1] = future
    future.set_result({"content": [{"type": "text", "text": "ack"}]})
    assert future.result() == {"content": [{"type": "text", "text": "ack"}]}
    # After resolution, _handle_mcp pops the future.
    ctx.pending_mcp_calls.pop(1)
    assert 1 not in ctx.pending_mcp_calls
    loop.close()
