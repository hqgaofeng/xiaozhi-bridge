"""Per-session MCP client (V2 #7.7 blueprint).

V2 #11a refactor: this class encapsulates the per-session MCP state
that was previously scattered across:

  - `SessionContext.pending_mcp_calls`  (dict[int, Future])
  - `SessionContext.mcp_request_id`     (int counter)
  - Global `_REGISTRY` in mcp/tools.py  (race condition source)

Why per-session: the old global `_REGISTRY` was overwritten by
every session (Bug 4 we found in V2 #7.7). The proper fix is
per-session MCPClient instances — each session gets its own,
the global registry becomes the SESSION's client, and races
become physically impossible.

The asyncio.Lock is belt-and-suspenders: it guards the in-memory
state mutations even within a single event loop (the lock
isn't strictly required in single-thread asyncio, but the
official `MCPClient` in 78/xiaozhi-esp32-server uses one and we
follow that pattern for forward-compat with future
multi-loop support).

Reference:
  78/xiaozhi-esp32-server main/xiaozhi-server/core/providers/tools/
  device_mcp/mcp_handler.py (MCPClient class, 403 lines, same design).

Design notes:
  - Holds the discovered tools, name mapping, in-flight call
    futures, and a monotonic request id counter.
  - Replaces the global `_REGISTRY` for DEVICE-type tools.
  - The FunctionTool path (V1) keeps using the global _REGISTRY
    for now — that's a single Python function with no race.
"""

from __future__ import annotations

import asyncio
from typing import Any


class MCPClient:
    """Per-session MCP client.

    Each connected device has one MCPClient instance. The instance
    is created in the server's `_handle_connection` (right after
    the session is constructed) and lives until the connection
    drops. Cleanup cancels any pending futures and drops the
    reference.

    The client does NOT send the JSON-RPC message itself — that's
    the server's job (it has the WebSocket). The client just
    tracks the in-flight state and resolves the future when the
    server's `_handle_mcp` (or its handler equivalent) sees the
    matching response.
    """

    def __init__(self) -> None:
        # Discovered tools, keyed by their bridge-side "friendly" name
        # (e.g. "set_volume"). The value is the full ToolSpec dict
        # from JSON-RPC `tools/list` — we don't need to parse it
        # here, the LLM gets the OpenAI-shape payload separately.
        self.tools: dict[str, dict[str, Any]] = {}

        # Bridge name → esp32 "physical" name (forward-compat).
        # Mirrors DeviceToolHandler.ESP32_NAME_MAP but is per-session
        # so each esp32 firmware version can have its own map.
        self.name_mapping: dict[str, str] = {}

        # In-flight JSON-RPC calls: id → Future that resolves with
        # the device's response (result or error). Popped by
        # resolve_call_result / reject_call_result.
        self.call_results: dict[int, asyncio.Future] = {}

        # Monotonic counter for JSON-RPC request ids. Per-session
        # so different sessions can use overlapping ids safely.
        self.next_id: int = 0

        # Whether the device has finished its initial tools/list
        # handshake and is ready to accept tools/call. We gate
        # outbound calls on this so the LLM doesn't try to call
        # tools that haven't been discovered yet.
        self.ready: bool = False

        # asyncio.Lock (V2 #7.7 race fix — see module docstring).
        self._lock = asyncio.Lock()

    async def register_tool(self, name: str, def_: dict[str, Any]) -> None:
        """Add a tool to this session's discovered set.

        Args:
            name: bridge-side friendly name (e.g. "set_volume").
            def_: full tool definition dict (the JSON-RPC tools/list
                entry) so we can build the OpenAI-shape payload
                later without re-asking the device.
        """
        async with self._lock:
            self.tools[name] = def_

    async def has_tool(self, name: str) -> bool:
        """Whether a tool with this name has been registered."""
        return name in self.tools

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Return the discovered tools as a list of OpenAI-shape
        function descriptions.

        Used by `_build_llm_tools_payload` to build the
        `tools=[...]` argument for the LLM.
        """
        return list(self.tools.values())

    async def get_next_id(self) -> int:
        """Reserve the next JSON-RPC request id for this session.

        Atomic with respect to register_call_result so a call
        can't be registered under a different id than the one
        that was just reserved.
        """
        async with self._lock:
            self.next_id += 1
            return self.next_id

    async def register_call_result(
        self, id: int, future: asyncio.Future
    ) -> None:
        """Stash the future for a call's eventual response.

        The future is what `_handle_mcp` resolves when the device
        sends back the matching JSON-RPC response.
        """
        async with self._lock:
            self.call_results[id] = future

    async def resolve_call_result(self, id: int, result: Any) -> None:
        """Mark a call as successfully completed (resolve the future).

        If the id is unknown (e.g. timeout already fired and the
        future was popped), this is a no-op — the call already
        returned to the LLM with an error and we don't want to
        raise a spurious "future already done" warning.
        """
        async with self._lock:
            future = self.call_results.pop(id, None)
        if future is not None and not future.done():
            future.set_result(result)

    async def reject_call_result(self, id: int, exc: Exception) -> None:
        """Mark a call as failed (set exception on the future).

        Same "unknown id is no-op" semantics as resolve_call_result.
        """
        async with self._lock:
            future = self.call_results.pop(id, None)
        if future is not None and not future.done():
            future.set_exception(exc)

    async def cleanup(self) -> None:
        """V2 #8.4: cancel all in-flight calls and reset state.

        Called from the connection's `finally` block. Any pending
        futures get a RuntimeError so the LLM tool-use coroutine
        unblocks with a clear reason (otherwise it would block
        until its 5s timeout fires, which delays the session
        teardown).
        """
        async with self._lock:
            pending = list(self.call_results.items())
            self.call_results.clear()
        for _id, future in pending:
            if not future.done():
                future.set_exception(
                    RuntimeError("session closed before mcp response")
                )

    def __repr__(self) -> str:
        return (
            f"MCPClient(tools={len(self.tools)}, "
            f"pending={len(self.call_results)}, ready={self.ready})"
        )
