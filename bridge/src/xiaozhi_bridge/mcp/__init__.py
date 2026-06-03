"""MCP (Model Context Protocol) server for the bridge.

Implements JSON-RPC 2.0 handling for the `type: "mcp"` message channel.
Used to discover and invoke device capabilities (volume, screen, etc.).
"""

from .server import MCPError, MCPServer
from .tools import call_tool, clear_tools, list_tools, register_tool, tool_spec_to_json

__all__ = [
    "MCPError",
    "MCPServer",
    "call_tool",
    "clear_tools",
    "list_tools",
    "register_tool",
    "tool_spec_to_json",
]
