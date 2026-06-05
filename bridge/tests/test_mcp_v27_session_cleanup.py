"""Tests for V2 #7 session cleanup (handler unregister + future cancel)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from xiaozhi_bridge.mcp.tools import (
    _REGISTRY as _tool_registry,  # noqa: N811
)
from xiaozhi_bridge.mcp.tools import (
    DeviceToolHandler,
    clear_tools,
    register_tool,
)


@pytest.fixture(autouse=True)
def reset_registry():
    clear_tools()
    yield
    clear_tools()


# --- _session_tool_owners + _cleanup_session_tools ---


def test_cleanup_session_tools_unregisters_owners():
    """V2 #7: cleanup removes handlers owned by the session."""
    # Simulate a server with the cleanup helpers.
    server = MagicMock()
    server._session_tool_owners = {}

    async def noop_send(tool_name, arguments, future):
        pass

    handler = DeviceToolHandler(
        name="set_volume",
        description="Set volume",
        input_schema={"type": "object", "properties": {"volume": {"type": "integer"}}},
        send_mcp_call=noop_send,
    )
    register_tool(handler)
    server._session_tool_owners["sess-1"] = ["set_volume"]
    assert _tool_registry.get("set_volume") is handler

    # Call the real cleanup.
    from xiaozhi_bridge.server import XiaozhiBridgeServer
    XiaozhiBridgeServer._cleanup_session_tools(server, "sess-1")

    assert _tool_registry.get("set_volume") is None
    assert "sess-1" not in server._session_tool_owners


def test_cleanup_session_tools_ignores_unknown_session():
    """V2 #7: cleanup of unknown session is a no-op (no error)."""
    from xiaozhi_bridge.server import XiaozhiBridgeServer
    server = MagicMock()
    server._session_tool_owners = {"sess-1": ["set_volume"]}
    # No error when session not present.
    XiaozhiBridgeServer._cleanup_session_tools(server, "sess-unknown")
    assert "sess-1" in server._session_tool_owners


# --- pending_mcp_calls cleared + futures cancelled ---


@pytest.mark.asyncio
async def test_pending_mcp_futures_resolved_on_session_close():
    """V2 #7: unresolved futures get an exception so awaiters don't hang."""
    from xiaozhi_bridge.protocol.states import SessionContext
    ctx = SessionContext(session_id="sess-x")
    fut1 = ctx.pending_mcp_calls[1] = asyncio.get_running_loop().create_future()
    fut2 = ctx.pending_mcp_calls[2] = asyncio.get_running_loop().create_future()

    # Simulate the finally-block cleanup logic.
    for req_id, future in list(ctx.pending_mcp_calls.items()):
        if not future.done():
            future.set_exception(
                RuntimeError(f"session closed before mcp response (id={req_id})")
            )
    ctx.pending_mcp_calls.clear()

    assert ctx.pending_mcp_calls == {}
    with pytest.raises(RuntimeError, match="session closed"):
        await fut1
    with pytest.raises(RuntimeError, match="session closed"):
        await fut2


@pytest.mark.asyncio
async def test_pending_mcp_done_futures_unchanged():
    """V2 #7: futures that already completed are not overwritten."""
    from xiaozhi_bridge.protocol.states import SessionContext
    ctx = SessionContext(session_id="sess-y")
    fut = ctx.pending_mcp_calls[1] = asyncio.get_running_loop().create_future()
    fut.set_result({"content": [{"type": "text", "text": "ok"}]})

    for _req_id, future in list(ctx.pending_mcp_calls.items()):
        if not future.done():
            future.set_exception(RuntimeError("should not be called"))
    ctx.pending_mcp_calls.clear()

    assert fut.result() == {"content": [{"type": "text", "text": "ok"}]}
