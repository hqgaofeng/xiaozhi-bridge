"""MCP message handler (V2 #11b).

V2 #11b refactor: extracted from server.py `_handle_mcp`
(53 lines). Behavior preserved 1:1.

MCP JSON-RPC 2.0 over xiaozhi WS has two cases:
  1. Request (has id, has method): device calls a bridge-side
     tool → forward to MCPServer.handle() and ship the
     response back.
  2. Response (no method, has id + result/error): device is
     answering an MCP call the bridge sent earlier
     (V2 #7 DeviceToolHandler). Resolve the matching
     pending future from session.pending_mcp_calls.
"""

from __future__ import annotations

from typing import Any

from ...protocol import MCPMessage, serialize_server_message
from ..textMessageHandler import TextMessageHandler


class McpTextMessageHandler(TextMessageHandler):
    """Handle `type: "mcp"` messages from the device."""

    message_type = "mcp"

    async def handle(
        self,
        conn: Any,
        ws: Any,
        session: Any,
        message: MCPMessage,
    ) -> None:
        payload = message.payload

        # Case 2: response — resolve a pending future.
        if "id" in payload and "method" not in payload:
            try:
                request_id = int(payload["id"])
            except (TypeError, ValueError):
                conn.log.warning("mcp.bad_response_id", payload=payload)
                return
            future = session.pending_mcp_calls.pop(request_id, None)
            if future is None or future.done():
                conn.log.warning(
                    "mcp.unknown_response",
                    request_id=request_id,
                    session_id=session.session_id,
                )
                return
            if "error" in payload:
                future.set_exception(RuntimeError(f"mcp error: {payload['error']}"))
            else:
                future.set_result(payload.get("result"))
            conn.log.info(
                "mcp.response_received",
                session_id=session.session_id,
                request_id=request_id,
            )
            return

        # Case 1: request — dispatch to MCPServer.
        conn.log.info("mcp.request_received", session_id=session.session_id)
        response = await conn.mcp.handle(payload)
        if response is not None:
            await ws.send(serialize_server_message(
                MCPMessage(session_id=session.session_id, payload=response)
            ))
