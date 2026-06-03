"""Tests for MCP JSON-RPC 2.0 server."""

import pytest

from xiaozhi_bridge.mcp import MCPServer
from xiaozhi_bridge.mcp.tools import clear_tools, register_function
from xiaozhi_bridge.mcp.server import JSONRPCErrorCode


@pytest.fixture(autouse=True)
def reset_tools():
    """Reset tool registry between tests."""
    clear_tools()

    @register_function(
        name="test.echo",
        description="Echo back the input",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    async def echo(text: str) -> str:
        return f"echo: {text}"

    yield
    clear_tools()


@pytest.mark.asyncio
async def test_initialize():
    server = MCPServer()
    resp = await server.handle({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    })
    assert resp["id"] == 1
    assert "protocolVersion" in resp["result"]
    assert resp["result"]["serverInfo"]["name"] == "xiaozhi-bridge"


@pytest.mark.asyncio
async def test_tools_list():
    server = MCPServer()
    resp = await server.handle({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    })
    assert resp["id"] == 2
    tool_names = [t["name"] for t in resp["result"]["tools"]]
    assert "test.echo" in tool_names


@pytest.mark.asyncio
async def test_tools_call_success():
    server = MCPServer()
    resp = await server.handle({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "test.echo",
            "arguments": {"text": "hello"},
        },
    })
    assert resp["id"] == 3
    assert resp["result"]["isError"] is False
    assert resp["result"]["content"][0]["text"] == "echo: hello"


@pytest.mark.asyncio
async def test_tools_call_unknown_tool():
    server = MCPServer()
    resp = await server.handle({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "nonexistent",
            "arguments": {},
        },
    })
    assert resp["id"] == 4
    assert "error" in resp
    assert resp["error"]["code"] == JSONRPCErrorCode.METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_unknown_method():
    server = MCPServer()
    resp = await server.handle({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "nonsense",
        "params": {},
    })
    assert resp["error"]["code"] == JSONRPCErrorCode.METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_invalid_jsonrpc_version():
    server = MCPServer()
    resp = await server.handle({
        "jsonrpc": "1.0",
        "id": 6,
        "method": "initialize",
        "params": {},
    })
    assert resp["error"]["code"] == JSONRPCErrorCode.INVALID_REQUEST


@pytest.mark.asyncio
async def test_notification_returns_none():
    """Notifications (no id) should not get a response."""
    server = MCPServer()
    resp = await server.handle({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    })
    assert resp is None
