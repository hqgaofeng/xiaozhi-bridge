"""Tool manager: registry + dispatch for tool executors (V2 #7.7).

V2 #11a refactor: this module replaces the global `_REGISTRY`
in mcp/tools.py with a proper ToolManager that:

  1. Categorizes tools by their execution location (DEVICE on
     esp32, FUNCTION locally in the bridge, etc.)
  2. Dispatches tool calls to the right executor
  3. Caches the tool-name → executor mapping for fast lookup

This is the V2 #7.7 complete fix for the race condition we
found in V2 #7 (Bug 4): the global dict could be overwritten
by concurrent sessions because DeviceToolHandler instances
held ws/session closures that became stale on reconnect.

Reference:
  78/xiaozhi-esp32-server main/xiaozhi-server/core/providers/tools/
  unified_tool_manager.py (ToolManager, 200+ lines, same design).

Why we don't just use 5 separate Executor classes (like the
official server): we currently only have 2 tool types
(DEVICE + FUNCTION). Adding the other 3 (SERVER_MCP,
DEVICE_IOT, MCP_ENDPOINT) is a V3 feature — for now we keep
the manager thin and the ToolType enum extensible.
"""

from __future__ import annotations

import abc
from enum import StrEnum
from typing import Any


class ToolType(StrEnum):
    """Tool categorization for executor dispatch.

    Mirrors the official server's ToolType (subset for our V2
    stage; SERVER/IOT/MCP_ENDPOINT are future).
    """

    DEVICE = "device"      # V2 #7: runs on esp32, forwards via JSON-RPC
    FUNCTION = "function"  # V1: runs as a Python function in the bridge
    # SERVER = "server"    # future: web_search, get_weather, etc.
    # IOT = "iot"          # future: HA / mqtt / 米家
    # MCP_ENDPOINT = "mcp_endpoint"  # future: external MCP server


class ToolExecutor(abc.ABC):
    """Abstract base for tool executors.

    Each executor owns one ToolType. The ToolManager dispatches
    a tool call to the executor whose type matches the tool's
    category.
    """

    tool_type: ToolType  # subclass sets this

    @abc.abstractmethod
    async def execute(
        self, name: str, arguments: dict[str, Any]
    ) -> Any:
        """Execute a tool by name and return the raw result.

        The ToolManager normalizes the result to a string for
        the role=tool message; executors can return whatever
        type makes sense (string, dict, list, etc.).
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_tools(self) -> dict[str, dict[str, Any]]:
        """Return the tools this executor knows about, keyed by
        bridge-side name. Each value is the OpenAI-shape
        function description dict.
        """
        raise NotImplementedError


class FunctionToolExecutor(ToolExecutor):
    """V1 executor: runs tools as Python functions (the legacy
    _REGISTRY in mcp/tools.py).

    Backed by the global `_REGISTRY` for now — the per-session
    migration for FunctionTool is out of scope (V2 #11a only
    addresses the DEVICE race). Future refactor: make
    FunctionTool also per-session, but it has no race today
    because Python function execution is synchronous and
    single-threaded in our event loop.
    """

    tool_type = ToolType.FUNCTION

    def execute(
        self, name: str, arguments: dict[str, Any]
    ) -> Any:
        """Synchronous wrapper — async delegated to call_tool.

        We import here (vs at module top) to avoid a circular
        import (manager.py would be imported by tools.py which
        imports manager.py).
        """
        # Imported lazily to avoid the circular import.
        # call_tool is async; ToolManager.execute_tool awaits
        # the result, so this method is technically a coroutine
        # wrapper. Returning the coroutine is safe — the
        # ToolManager awaits it.

        from . import tools as _tools
        return _tools.call_tool(name, arguments)

    def get_tools(self) -> dict[str, dict[str, Any]]:
        """Delegate to the global list_tools (V1 path)."""
        from . import tools as _tools
        result: dict[str, dict[str, Any]] = {}
        for spec in _tools.list_tools():
            result[spec["name"]] = {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["inputSchema"],
            }
        return result


class DeviceMCPExecutor(ToolExecutor):
    """V2 #7 executor: forwards tool calls to esp32 over the
    xiaozhi MCP channel and awaits the device's response.

    The actual JSON-RPC send is delegated to the server (which
    has the WebSocket). This executor just:

      1. Translates the bridge-side name to the esp32 "physical"
         name (via the per-session name_mapping)
      2. Builds the JSON-RPC payload
      3. Asks the server to ship it and stash the future
      4. Awaits the future

    Why the indirection: the server's `_handle_mcp` resolves
    the future when the matching response arrives. Putting
    that logic in the executor would require a reverse
    reference to the message loop, which is uglier than the
    current "executor asks server to send" pattern.
    """

    tool_type = ToolType.DEVICE

    def __init__(self) -> None:
        # The server fills this in once it has a session + ws.
        # We keep it as None until then; the manager's
        # dispatch is a no-op for tools with no sender bound.
        self._send_fn: Any = None
        # name → bridge-side friendly → esp32 physical map.
        # Filled by the server's _register_device_tools.
        self._name_mapping: dict[str, str] = {}

    def bind(
        self,
        send_fn: Any,
        name_mapping: dict[str, str],
    ) -> None:
        """Bind the WebSocket sender + name map for this session.

        Called from server._register_device_tools after the
        session + ws are known.
        """
        self._send_fn = send_fn
        self._name_mapping = dict(name_mapping)

    async def execute(
        self, name: str, arguments: dict[str, Any]
    ) -> Any:
        """Forward a tool call to esp32 and await the response.

        Returns the esp32's result (typically a string from
        content[0].text or a parsed dict). Raises on timeout
        or JSON-RPC error (DeviceToolHandler raises; we
        re-raise so the ToolManager can normalize the error
        message).
        """
        if self._send_fn is None:
            raise RuntimeError("DeviceMCPExecutor not bound to a session")
        esp32_name = self._name_mapping.get(name, name)
        # send_fn is a 3-arg callable: (esp32_name, arguments, future).
        # It returns the future that resolves when the response
        # arrives. We await it (with the handler's timeout —
        # DeviceToolHandler wraps this with asyncio.wait_for).
        import asyncio
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self._send_fn(esp32_name, arguments, future)
        return await future

    def get_tools(self) -> dict[str, dict[str, Any]]:
        """Return the registered device tools (OpenAI shape).

        The map is filled by the server's _register_device_tools.
        Returns whatever's bound so far (empty if not bound).
        """
        # We don't actually store the full defs here — the
        # server keeps them in the per-session MCPClient.
        # For the LLM tools payload, the manager uses the
        # DEVICE executor's get_tools as a fallback; the
        # server's _build_llm_tools_payload is the
        # authoritative source for DEVICE tools.
        return {}


class ToolManager:
    """Registry + dispatch for tool executors.

    Holds the registered executors (one per ToolType) and
    dispatches a tool call to the right executor. Each tool
    name → executor mapping is cached for fast lookup.
    """

    def __init__(self) -> None:
        self.executors: dict[ToolType, ToolExecutor] = {}
        # Cache: tool_name → executor. Invalidated by
        # _invalidate_cache when an executor is registered.
        # We don't store per-tool schemas here — the executor
        # knows its own tools via get_tools().
        self._tool_to_executor: dict[str, ToolExecutor] = {}
        self._cache_valid: bool = False

    def register_executor(
        self, type_: ToolType, executor: ToolExecutor
    ) -> None:
        """Register a tool executor for a given type.

        Re-registration replaces the old one (idempotent).
        Invalidates the tool-name → executor cache.
        """
        self.executors[type_] = executor
        self._cache_valid = False

    def _rebuild_cache(self) -> None:
        """Walk all executors' get_tools() to populate the cache."""
        cache: dict[str, ToolExecutor] = {}
        for executor in self.executors.values():
            try:
                for tool_name in executor.get_tools():
                    cache[tool_name] = executor
            except Exception:
                # Executor shouldn't fail at registration time;
                # if it does, skip it (the manager will log
                # when it tries to dispatch and finds no
                # executor).
                continue
        self._tool_to_executor = cache
        self._cache_valid = True

    def get_executor(self, name: str) -> ToolExecutor | None:
        """Look up the executor for a tool by name.

        Returns None if the tool is unknown. Walks the cache
        and rebuilds it lazily if it was invalidated.
        """
        if not self._cache_valid:
            self._rebuild_cache()
        return self._tool_to_executor.get(name)

    async def execute_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Any:
        """Dispatch a tool call to the matching executor.

        The return value is whatever the executor's execute()
        returns. Errors are propagated; the caller (the server's
        _dispatch_tool) normalizes them to a string for the
        LLM's role=tool message.
        """
        executor = self.get_executor(name)
        if executor is None:
            raise KeyError(f"Unknown tool: {name!r}")
        return await executor.execute(name, arguments)

    def list_all_tools(self) -> list[dict[str, Any]]:
        """Return all tools from all executors in OpenAI shape.

        Used by the LLM to populate the `tools=[...]` array.
        Cached like the name→executor map.
        """
        if not self._cache_valid:
            self._rebuild_cache()
        all_tools: list[dict[str, Any]] = []
        for executor in self.executors.values():
            all_tools.extend(executor.get_tools().values())
        return all_tools
