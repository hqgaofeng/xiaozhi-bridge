"""MCP (Model Context Protocol) server for the bridge.

Implements JSON-RPC 2.0 handling for the `type: "mcp"` message channel.
Used to discover and invoke device capabilities (volume, screen, etc.).
"""

from .server import MCPServer, MCPError
from .tools import register_tool, list_tools, call_tool, clear_tools, tool_spec_to_json

__all__ = [
    "MCPServer",
    "MCPError",
    "register_tool",
    "list_tools",
    "call_tool",
    "clear_tools",
    "tool_spec_to_json",
]
