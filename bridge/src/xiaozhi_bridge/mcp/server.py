"""MCP JSON-RPC 2.0 server.

Handles incoming MCP messages from the device (or openclaw).
Implements the JSON-RPC 2.0 spec:

  - Request:  { jsonrpc, id, method, params }
  - Response: { jsonrpc, id, result | error }
  - Notification (no id): { jsonrpc, method, params }

Reference: https://www.jsonrpc.org/specification
"""

from __future__ import annotations

import logging
from typing import Any

from . import tools as tool_registry

log = logging.getLogger(__name__)


# --- JSON-RPC 2.0 standard error codes ---


class JSONRPCErrorCode:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class MCPError(Exception):
    """An MCP-level error (wraps a JSON-RPC error code)."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


class MCPServer:
    """JSON-RPC 2.0 server for MCP.

    Methods implemented:
      - initialize: handshake
      - tools/list: list available tools
      - tools/call: invoke a tool
    """

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "xiaozhi-bridge"
    SERVER_VERSION = "0.1.0"

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Handle an incoming JSON-RPC 2.0 message.

        Returns:
            - A response dict if the message is a request (has id).
            - None if the message is a notification (no id).
        """
        # Validate
        if payload.get("jsonrpc") != "2.0":
            return self._error(
                None,
                JSONRPCErrorCode.INVALID_REQUEST,
                "jsonrpc must be '2.0'",
            )

        method = payload.get("method")
        if not method:
            return self._error(
                payload.get("id"),
                JSONRPCErrorCode.INVALID_REQUEST,
                "missing method",
            )

        params = payload.get("params", {}) or {}
        request_id = payload.get("id")

        try:
            match method:
                case "initialize":
                    result = await self._handle_initialize(params)
                case "tools/list":
                    result = await self._handle_tools_list(params)
                case "tools/call":
                    result = await self._handle_tools_call(params)
                case "notifications/initialized":
                    # client confirms it's ready; no response
                    log.info("mcp.initialized_received")
                    return None
                case _:
                    return self._error(
                        request_id,
                        JSONRPCErrorCode.METHOD_NOT_FOUND,
                        f"Unknown method: {method}",
                    )
        except MCPError as e:
            return self._error(request_id, e.code, e.message, e.data)
        except Exception as e:
            log.exception("mcp.internal_error", method=method)
            return self._error(
                request_id,
                JSONRPCErrorCode.INTERNAL_ERROR,
                f"Internal error: {e!r}",
            )

        if request_id is None:
            # Notification — no response
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    # --- Method handlers ---

    async def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": self.SERVER_NAME,
                "version": self.SERVER_VERSION,
            },
        }

    async def _handle_tools_list(self, params: dict) -> dict:
        cursor = params.get("cursor", "")
        with_user_tools = params.get("withUserTools", False)
        all_tools = tool_registry.list_tools(with_user_tools=with_user_tools)
        # V1: no pagination, all tools returned at once
        # V2: respect cursor and return nextCursor
        return {
            "tools": all_tools,
            "nextCursor": "",
        }

    async def _handle_tools_call(self, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        if not name:
            raise MCPError(JSONRPCErrorCode.INVALID_PARAMS, "missing 'name'")
        try:
            result = await tool_registry.call_tool(name, arguments)
        except KeyError as e:
            raise MCPError(JSONRPCErrorCode.METHOD_NOT_FOUND, str(e))
        except TypeError as e:
            raise MCPError(JSONRPCErrorCode.INVALID_PARAMS, str(e))

        # Wrap result per MCP convention: content array
        return {
            "content": [{"type": "text", "text": str(result)}],
            "isError": False,
        }

    # --- Helpers ---

    def _error(
        self, request_id: Any, code: int, message: str, data: Any = None
    ) -> dict:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": err}
