"""LLM client abstract base class.

The bridge talks to an LLM via this interface. The default implementation
calls the openclaw gateway's Anthropic-compatible /v1/messages endpoint.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

# --- Data types ---


@dataclass
class Message:
    """One message in a chat history."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # For tool messages
    tool_call_id: str | None = None
    name: str | None = None
    # For assistant messages with tool calls
    tool_calls: list[dict] | None = None


@dataclass
class Tool:
    """A tool (function) the LLM can call.

    OpenAI-style function spec: name, description, parameters (JSON Schema).
    """

    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments


@dataclass
class LLMEvent:
    """A streamed event from the LLM.

    - TEXT: incremental text content
    - TOOL_CALL: the LLM decided to call a tool
    - TOOL_CALL_DELTA: partial tool call (for streaming)
    - DONE: generation finished
    - ERROR: error occurred
    """

    kind: str  # "text" | "tool_call" | "tool_call_delta" | "done" | "error"
    text: str = ""
    tool_call: dict | None = None
    tool_call_delta: dict | None = None
    finish_reason: str | None = None
    error: str | None = None


# --- Abstract client ---


class LLMClient(abc.ABC):
    """Abstract LLM client."""

    name: str = "base"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}

    @abc.abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """Stream a chat completion.

        Args:
            messages: Chat history (in chronological order).
            tools: Optional list of tools the LLM can call.
            system: Optional system prompt (separate from messages).

        Yields:
            LLMEvent instances.
        """
        raise NotImplementedError
        yield  # type: ignore


# --- Registry ---


_REGISTRY: dict[str, type[LLMClient]] = {}


def register_llm(name: str):
    def decorator(cls: type[LLMClient]) -> type[LLMClient]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_llm(name: str, options: dict[str, Any] | None = None) -> LLMClient:
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "(none)"
        raise KeyError(f"Unknown LLM provider: {name!r}. Available: {available}")
    return _REGISTRY[name](options=options)


def list_llm_providers() -> list[str]:
    return sorted(_REGISTRY.keys())
