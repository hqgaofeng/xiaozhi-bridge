"""MCP tool registry.

Tools are functions the device can invoke (and the LLM can use via the bridge).
Examples:
- self.get_device_status  → query device status
- self.audio_speaker.set_volume → set speaker volume
- self.screen.set_brightness → set screen brightness

In our setup, these get bridged to actual device MCP calls OR
openclaw-side tool calls (for off-board capabilities like IoT).
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Specification of a tool (for JSON-RPC tools/list)."""

    name: str
    description: str
    input_schema: dict  # JSON Schema


class ToolHandler(abc.ABC):
    """Abstract base for tool handlers."""

    name: str
    description: str
    input_schema: dict

    @abc.abstractmethod
    async def __call__(self, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError


class FunctionTool(ToolHandler):
    """Wrap a Python function as a tool handler."""

    def __init__(self, name: str, description: str, input_schema: dict, func: Callable[..., Awaitable[Any]]):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.func = func

    async def __call__(self, arguments: dict[str, Any]) -> Any:
        return await self.func(**arguments)


# --- Registry ---


_REGISTRY: dict[str, ToolHandler] = {}


def register_tool(handler: ToolHandler) -> None:
    """Register a tool handler."""
    _REGISTRY[handler.name] = handler
    log.debug("tool.registered", name=handler.name)


def register_function(
    name: str,
    description: str,
    input_schema: dict,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to register an async function as a tool.

    Usage:
        @register_function("self.get_device_status", "...", {...})
        async def get_device_status(...) -> str:
            ...
    """
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        register_tool(FunctionTool(name, description, input_schema, func))
        return func

    return decorator


def list_tools(with_user_tools: bool = False) -> list[dict]:
    """Return the list of tools in MCP format.

    If with_user_tools is False, hide user-only tools (privileged).
    """
    tools = []
    for handler in _REGISTRY.values():
        # V1: no user-only tools yet, all are regular
        if not with_user_tools and getattr(handler, "user_only", False):
            continue
        tools.append({
            "name": handler.name,
            "description": handler.description,
            "inputSchema": handler.input_schema,
        })
    return tools


async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Call a tool by name with the given arguments."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown tool: {name}")
    handler = _REGISTRY[name]
    log.info("tool.call", name=name, arguments=arguments)
    try:
        result = await handler(arguments)
    except Exception:
        log.exception("tool.error", name=name)
        raise
    return result


def clear_tools() -> None:
    """Clear all registered tools (for testing)."""
    _REGISTRY.clear()


def tool_spec_to_json(handler: ToolHandler) -> dict:
    """Convert a tool handler to MCP JSON-RPC tool spec."""
    return {
        "name": handler.name,
        "description": handler.description,
        "inputSchema": handler.input_schema,
    }


# --- Built-in tools (V1) ---


@register_function(
    name="self.get_device_status",
    description="获取设备当前状态（音量、亮度、Wi-Fi 等）",
    input_schema={
        "type": "object",
        "properties": {},
    },
)
async def get_device_status() -> dict:
    """Return current device status (mock for V1)."""
    return {
        "volume": 50,
        "brightness": 80,
        "wifi_connected": True,
        "battery": 100,
    }


@register_function(
    name="self.audio_speaker.set_volume",
    description="设置扬声器音量（0-100）",
    input_schema={
        "type": "object",
        "properties": {
            "volume": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": ["volume"],
    },
)
async def set_volume(volume: int) -> bool:
    """Set speaker volume. V1: just record the request."""
    log.info("device.volume_set", volume=volume)
    # V1: send to device via MCP response; V2: actually control hardware
    return True


@register_function(
    name="self.led.set_rgb",
    description="设置板载 LED 颜色",
    input_schema={
        "type": "object",
        "properties": {
            "r": {"type": "integer", "minimum": 0, "maximum": 255},
            "g": {"type": "integer", "minimum": 0, "maximum": 255},
            "b": {"type": "integer", "minimum": 0, "maximum": 255},
        },
        "required": ["r", "g", "b"],
    },
)
async def set_led_rgb(r: int, g: int, b: int) -> bool:
    """Set onboard LED color. V1: log only."""
    log.info("device.led_rgb", r=r, g=g, b=b)
    return True
