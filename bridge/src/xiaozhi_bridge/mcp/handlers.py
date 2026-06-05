"""MCP message handlers — bridge→esp32 side.

V2 #11a refactor: 5 methods from server.py are consolidated here
so the server file can focus on connection lifecycle.

The methods extracted (all V2 #7):
  - _send_mcp_call         → send_call (async)
  - _register_device_tools → register_tools (sync)
  - _cleanup_session_tools → cleanup_tools (sync)
  - _build_llm_tools_payload → build_llm_tools_payload (sync)
  - _dispatch_tool         → dispatch (async)

All methods take a `server` argument which is a thin wrapper
around XiaozhiBridgeServer — we deliberately avoid a
`from .server import ...` to keep this module's import graph
acyclic. The wrapper is just an interface (the methods only
need ws, session, log, and the tool registry).

The V2 #7 tests (test_mcp_v27*.py) still call
`XiaozhiBridgeServer._cleanup_session_tools(server, ...)` —
we keep that as a thin shim that delegates here.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .manager import DeviceMCPExecutor, ToolManager
from .tools import (
    DeviceToolHandler,
    register_tool,
    unregister_tool,
)

# --- 1. send_call (V2 #7 send_mcp_call) ---


async def send_mcp_call(
    server: Any,
    ws: Any,
    session: Any,
    tool_name: str,
    arguments: dict[str, Any],
    future: asyncio.Future,
) -> None:
    """Send a JSON-RPC `tools/call` to the device and register future.

    The future is stored in session.pending_mcp_calls and
    resolved by _handle_mcp when the matching response arrives.

    V2 #7 design: the request id is allocated from the session's
    monotonic counter so different sessions can use overlapping
    ids safely. The future dance: tool __call__ awaits the future;
    the future is resolved in _handle_mcp when the device sends
    the JSON-RPC response.

    Args:
        server: XiaozhiBridgeServer (for log + session lookup).
        ws: the WebSocket to ship the JSON-RPC message on.
        session: SessionContext (for pending_mcp_calls + mcp_request_id).
        tool_name: the bridge-side name (e.g. "set_volume"); the
            device-name map translates it to the esp32 physical name.
        arguments: JSON-RPC params.arguments.
        future: the future to resolve when the device replies.
    """
    session.mcp_request_id += 1
    request_id = session.mcp_request_id
    session.pending_mcp_calls[request_id] = future
    # Import here to avoid circular import at module load.
    from ..protocol import MCPMessage, serialize_server_message
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    await ws.send(serialize_server_message(
        MCPMessage(session_id=session.session_id, payload=payload)
    ))
    server.log.info(
        "mcp.call_sent",
        session_id=session.session_id,
        request_id=request_id,
        tool=tool_name,
    )


# --- 2. register_device_tools (V2 #7 _register_device_tools) ---


def register_device_tools(
    server: Any,
    session: Any,
    ws: Any,
    device_executor: DeviceMCPExecutor,
) -> list[str]:
    """V2 #7: register esp32-side tools as LLM-callable MCP tools.

    Each DeviceToolHandler holds a closure over `send_mcp_call`
    bound to this session's ws. When the LLM emits a tool_use
    for one of these names, the bridge ships a JSON-RPC
    `tools/call` to esp32 and awaits the response.

    V2 #11a: we ALSO bind the DeviceMCPExecutor's name_mapping
    so the ToolManager dispatch path can find the right esp32
    name for each tool.

    Returns:
        List of registered tool names (used for cleanup).
    """
    owned: list[str] = []

    async def _send(tool_name: str, arguments: dict, future: asyncio.Future) -> None:
        await send_mcp_call(server, ws, session, tool_name, arguments, future)

    def _register(handler: DeviceToolHandler) -> None:
        register_tool(handler)
        owned.append(handler.name)

    _register(DeviceToolHandler(
        name="get_device_status",
        description="获取设备当前状态（音量、亮度、Wi-Fi、电池等）",
        input_schema={"type": "object", "properties": {}},
        send_mcp_call=_send,
    ))
    _register(DeviceToolHandler(
        name="set_volume",
        description="设置扬声器音量（0-100）。修改后 esp32 会即时生效。",
        input_schema={
            "type": "object",
            "properties": {
                "volume": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": ["volume"],
        },
        send_mcp_call=_send,
    ))
    _register(DeviceToolHandler(
        name="set_brightness",
        description="设置屏幕亮度（0-100）。如果当前亮度未知，先调 get_device_status。",
        input_schema={
            "type": "object",
            "properties": {
                "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": ["brightness"],
        },
        send_mcp_call=_send,
    ))

    # V2 #11a: bind the per-session name mapping to the executor.
    # DeviceToolHandler.ESP32_NAME_MAP is the class-level default
    # (bridge "logical" → esp32 "physical"); we mirror it for
    # the manager's dispatch path.
    name_mapping = {
        "get_device_status": "self.get_device_status",
        "set_volume": "self.audio_speaker.set_volume",
        "set_brightness": "self.screen.set_brightness",
        "set_rgb": "self.led.set_rgb",
    }
    device_executor.bind(_send, name_mapping)

    # Persist ownership so cleanup can find the right tool set.
    if not hasattr(server, "_session_tool_owners"):
        server._session_tool_owners = {}
    server._session_tool_owners[session.session_id] = owned

    server.log.info(
        "device_tools.registered",
        session_id=session.session_id,
        tools=["get_device_status", "set_volume", "set_brightness"],
    )
    return owned


# --- 3. cleanup_session_tools (V2 #7 _cleanup_session_tools) ---


def cleanup_session_tools(server: Any, session_id: str) -> None:
    """V2 #7: unregister the device-tool handlers owned by session_id.

    Called from the connection's `finally` block to prevent
    stale handlers (with old ws/session closures) from
    leaking into future sessions. This is a stopgap; the
    proper fix is per-session MCPClient + DeviceMCPExecutor
    (V2 #7.7, partly done in V2 #11a).
    """
    if not hasattr(server, "_session_tool_owners"):
        return
    owned = server._session_tool_owners.pop(session_id, [])
    for name in owned:
        try:
            unregister_tool(name)
        except Exception:
            server.log.warning("device_tool.unregister_failed", name=name)
    if owned:
        server.log.info(
            "device_tools.unregistered",
            session_id=session_id,
            tools=owned,
        )


# --- 4. build_llm_tools_payload (V2 #7 _build_llm_tools_payload) ---


def build_llm_tools_payload(tool_manager: ToolManager) -> list[dict]:
    """V2 #7: build the OpenAI `tools` array from the MCP registry.

    Returns an empty list if no tools are registered (LLM
    just produces text). The returned shape is the OpenAI
    chat completions spec: [{"type": "function", "function": {...}}].

    V2 #11a: now uses ToolManager.list_all_tools() instead of
    the global _REGISTRY directly.
    """
    return tool_manager.list_all_tools()


# --- 5. dispatch_tool (V2 #7 _dispatch_tool) ---


async def dispatch_tool(
    server: Any,
    session: Any,
    name: str,
    arguments: dict,
    tool_manager: ToolManager,
) -> str:
    """V2 #7: invoke a tool by name and return a text result.

    Two execution paths:
      1. DeviceToolHandler (e.g. set_volume): forwards to esp32
         via the xiaozhi MCP channel and awaits the device's
         response. V2 #11a: this now goes through
         ToolManager.execute_tool → DeviceMCPExecutor.execute.
      2. FunctionTool (e.g. get_device_status in V1 mock): runs
         a Python function locally via the FunctionToolExecutor.

    Errors are normalized to a string for the role=tool message
    (the LLM sees "Error: tool X failed: ..." and can decide
    how to recover).
    """
    try:
        result = await tool_manager.execute_tool(name, arguments)
    except KeyError:
        server.log.warning("tool.unknown", name=name)
        return f"Error: tool {name!r} not found"
    except Exception as e:
        server.log.exception("tool.failed", name=name)
        return f"Error: tool {name!r} failed: {e!r}"
    # Normalize the result to a string for the role=tool message.
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)
