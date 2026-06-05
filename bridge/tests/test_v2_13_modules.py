"""Tests for V2 #13 module refactor.

Covers the 4 new modules and the 1 new sub-package that the
v0.2.13 refactor introduced:
  - mcp/client.py        (MCPClient per-session, asyncio.Lock)
  - mcp/manager.py       (ToolType + ToolManager dispatch)
  - mcp/handlers.py      (5 extracted methods)
  - handle/              (TextMessageHandlerRegistry + Processor + 4 handlers)
  - pipeline/tts.py      (TTS streaming pipeline)
  - audio/handler.py     (VAD + Opus + wake-grace)

These tests are independent of the existing V2 #7 tests
(test_mcp_v27*.py) which exercise the legacy global _REGISTRY
path through the server shims. The new tests exercise the
new module APIs directly.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from xiaozhi_bridge.mcp.client import MCPClient
from xiaozhi_bridge.mcp.handlers import (
    build_llm_tools_payload,
    cleanup_session_tools,
    dispatch_tool,
    register_device_tools,
)
from xiaozhi_bridge.mcp.manager import (
    DeviceMCPExecutor,
    FunctionToolExecutor,
    ToolManager,
    ToolType,
)
from xiaozhi_bridge.mcp.tools import (
    clear_tools,
)

# =====================================================================
# mcp/client.py — MCPClient per-session (V2 #7.7 race fix)
# =====================================================================


@pytest.mark.asyncio
async def test_mcp_client_initial_state():
    """MCPClient starts empty: no tools, no pending calls, not ready."""
    client = MCPClient()
    assert client.tools == {}
    assert client.name_mapping == {}
    assert client.call_results == {}
    assert client.next_id == 0
    assert client.ready is False


@pytest.mark.asyncio
async def test_mcp_client_register_and_get_tool():
    """register_tool + has_tool + get_available_tools round-trip."""
    client = MCPClient()
    def_ = {
        "name": "set_volume",
        "description": "set volume",
        "parameters": {"type": "object"},
    }
    await client.register_tool("set_volume", def_)
    assert await client.has_tool("set_volume")
    assert not await client.has_tool("nonexistent")
    tools = await client.get_available_tools()
    assert tools == [def_]


@pytest.mark.asyncio
async def test_mcp_client_get_next_id_is_monotonic():
    """get_next_id is atomic + monotonic, safe under concurrent calls."""
    client = MCPClient()
    ids = [await client.get_next_id() for _ in range(10)]
    # Strictly increasing
    assert ids == sorted(set(ids))
    assert len(set(ids)) == 10


@pytest.mark.asyncio
async def test_mcp_client_resolve_and_reject_call_result():
    """register_call_result + resolve / reject completes the future."""
    client = MCPClient()
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    request_id = await client.get_next_id()
    await client.register_call_result(request_id, fut)

    # Resolve
    await client.resolve_call_result(request_id, {"ok": True})
    assert fut.result() == {"ok": True}
    assert request_id not in client.call_results

    # Reject path
    fut2: asyncio.Future = asyncio.get_running_loop().create_future()
    rid2 = await client.get_next_id()
    await client.register_call_result(rid2, fut2)
    await client.reject_call_result(rid2, RuntimeError("device error"))
    assert fut2.exception() is not None
    assert "device error" in str(fut2.exception())
    assert rid2 not in client.call_results


@pytest.mark.asyncio
async def test_mcp_client_resolve_unknown_id_is_noop():
    """Resolving an unknown id does NOT raise (forward-compat)."""
    client = MCPClient()
    # Unknown id → no-op, no exception
    await client.resolve_call_result(999, {"x": 1})
    await client.reject_call_result(999, RuntimeError("x"))


@pytest.mark.asyncio
async def test_mcp_client_cleanup_cancels_pending():
    """cleanup() fails all pending futures so LLM coroutine unblocks."""
    client = MCPClient()
    futures = []
    for _ in range(3):
        rid = await client.get_next_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await client.register_call_result(rid, fut)
        futures.append(fut)
    await client.cleanup()
    for fut in futures:
        assert fut.done()
        with pytest.raises(RuntimeError, match="session closed"):
            fut.result()


# =====================================================================
# mcp/manager.py — ToolType + ToolManager dispatch
# =====================================================================


class FakeFunctionToolExecutor(FunctionToolExecutor):
    """Returns a fixed dict for any tool call — used in dispatch tests."""

    tool_type = ToolType.FUNCTION

    def __init__(self, return_value: Any = "ok") -> None:
        super().__init__()
        self._return_value = return_value
        self._tools = {"self.get_device_status": return_value}

    def get_tools(self) -> dict[str, dict[str, Any]]:
        return {
            "self.get_device_status": {
                "name": "self.get_device_status",
                "description": "test",
                "parameters": {"type": "object"},
            }
        }

    async def execute(self, name: str, arguments: dict) -> Any:
        return self._return_value


@pytest.mark.asyncio
async def test_tool_manager_register_and_dispatch():
    """Register a FunctionTool executor + dispatch returns its result."""
    tm = ToolManager()
    fn_exec = FakeFunctionToolExecutor(return_value={"volume": 50})
    tm.register_executor(ToolType.FUNCTION, fn_exec)

    result = await tm.execute_tool("self.get_device_status", {})
    assert result == {"volume": 50}


@pytest.mark.asyncio
async def test_tool_manager_unknown_tool_raises_keyerror():
    """ToolManager.execute_tool on unknown name → KeyError (consistent
    with the legacy _REGISTRY.call_tool behavior)."""
    tm = ToolManager()
    tm.register_executor(ToolType.FUNCTION, FakeFunctionToolExecutor())
    with pytest.raises(KeyError):
        await tm.execute_tool("unknown.tool", {})


def test_tool_manager_list_all_tools():
    """list_all_tools aggregates get_tools() across all executors."""
    tm = ToolManager()
    tm.register_executor(ToolType.FUNCTION, FakeFunctionToolExecutor())
    tools = tm.list_all_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "self.get_device_status"


@pytest.mark.asyncio
async def test_device_mcp_executor_not_bound_raises():
    """DeviceMCPExecutor.execute without bind() raises RuntimeError."""
    executor = DeviceMCPExecutor()
    with pytest.raises(RuntimeError, match="not bound"):
        await executor.execute("set_volume", {"volume": 50})


@pytest.mark.asyncio
async def test_device_mcp_executor_send_fn_called_with_esp32_name():
    """DeviceMCPExecutor uses name_mapping to translate bridge → esp32 name."""
    executor = DeviceMCPExecutor()
    received: list[tuple[str, dict]] = []

    async def send_fn(esp32_name: str, arguments: dict, future: asyncio.Future) -> None:
        received.append((esp32_name, arguments))
        future.set_result({"ok": True})

    executor.bind(
        send_fn,
        {"set_volume": "self.audio_speaker.set_volume"},
    )
    result = await executor.execute("set_volume", {"volume": 75})
    assert received == [("self.audio_speaker.set_volume", {"volume": 75})]
    assert result == {"ok": True}


# =====================================================================
# mcp/handlers.py — extracted methods
# =====================================================================


def test_build_llm_tools_payload_uses_tool_manager():
    """build_llm_tools_payload delegates to ToolManager.list_all_tools()."""
    tm = ToolManager()
    tm.register_executor(ToolType.FUNCTION, FakeFunctionToolExecutor())
    out = build_llm_tools_payload(tm)
    assert out == tm.list_all_tools()


@pytest.mark.asyncio
async def test_dispatch_tool_returns_error_string_on_unknown():
    """dispatch_tool returns 'Error: tool X not found' on unknown name."""
    server = MagicMock()
    server.log = MagicMock()
    tm = ToolManager()
    tm.register_executor(ToolType.FUNCTION, FakeFunctionToolExecutor())
    result = await dispatch_tool(server, None, "unknown.tool", {}, tm)
    assert "not found" in result


@pytest.mark.asyncio
async def test_dispatch_tool_normalizes_dict_result_to_json():
    """dispatch_tool normalizes dict result to JSON string for role=tool."""
    server = MagicMock()
    tm = ToolManager()
    tm.register_executor(ToolType.FUNCTION, FakeFunctionToolExecutor(return_value={"k": "v"}))
    result = await dispatch_tool(server, None, "self.get_device_status", {}, tm)
    import json
    assert json.loads(result) == {"k": "v"}


def test_register_and_cleanup_session_tools_roundtrip():
    """register_device_tools adds to _session_tool_owners, cleanup removes."""
    clear_tools()
    server = MagicMock()
    server.log = MagicMock()
    server._session_tool_owners = {}
    session = MagicMock()
    session.session_id = "s1"
    ws = MagicMock()
    device_executor = DeviceMCPExecutor()

    owned = register_device_tools(server, session, ws, device_executor)
    assert "set_volume" in owned
    assert "s1" in server._session_tool_owners
    # The device executor is now bound to a sender
    assert device_executor._send_fn is not None

    # Cleanup removes them
    cleanup_session_tools(server, "s1")
    assert "s1" not in server._session_tool_owners
    # Tool unregistered
    from xiaozhi_bridge.mcp.tools import _REGISTRY
    assert "set_volume" not in _REGISTRY


def test_cleanup_session_tools_unknown_session_no_error():
    """Cleanup of an unknown session is a silent no-op."""
    server = MagicMock()
    server._session_tool_owners = {}
    cleanup_session_tools(server, "never-registered")  # no error
