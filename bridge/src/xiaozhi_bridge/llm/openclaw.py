"""OpenClaw LLM client.

Calls the openclaw gateway's Anthropic-compatible /v1/messages endpoint.
OpenClaw is configured to use MiniMax M3 by default.

Why openclaw and not direct MiniMax API:
- We want tool calling (openclaw provides MCP tool integration)
- We want memory, future extensions
- We want centralized auth (one MiniMax key in openclaw config)

Reference: ../../../docs/architecture.md (LLM section)
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import LLMClient, LLMEvent, Message, Tool, register_llm

log = logging.getLogger(__name__)


@register_llm("openclaw")
class OpenClawLLM(LLMClient):
    """LLM client that calls openclaw gateway.

    Uses the Anthropic-compatible /v1/messages endpoint.
    OpenClaw handles the actual model selection and MiniMax auth.
    """

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(options)
        self.base_url = self.options.get("base_url", "http://127.0.0.1:18789")
        self.api_key = self.options.get("api_key", "")
        self.model = self.options.get("model", "minimax/MiniMax-M3")
        self.max_tokens = int(self.options.get("max_tokens", 4096))
        self.temperature = float(self.options.get("temperature", 0.7))
        self.timeout = float(self.options.get("timeout", 60.0))
        self.stream = bool(self.options.get("stream", True))

        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system: str | None = None,
    ) -> dict:
        """Build Anthropic-format request payload."""
        # Anthropic format: system is separate, messages are user/assistant only
        # Tool results are sent as user messages with tool_result blocks.
        # Tool calls in assistant messages are content blocks.

        api_messages = []
        for msg in messages:
            if msg.role == "system":
                # handled by separate system field
                continue
            elif msg.role == "tool":
                # tool result → user message with tool_result block
                api_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content,
                        }
                    ],
                })
            elif msg.role == "assistant" and msg.tool_calls:
                # assistant message with tool_use blocks
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": tc.get("name"),
                        "input": tc.get("arguments", {}),
                    })
                api_messages.append({"role": "assistant", "content": content})
            else:
                api_messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": api_messages,
            "stream": self.stream,
        }
        if system:
            payload["system"] = system

        # Convert tools to Anthropic format
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        return payload

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """Stream chat completion from openclaw."""
        client = await self._get_client()
        payload = self._build_payload(messages, tools, system)

        if not self.stream:
            # Non-streaming path
            payload["stream"] = False
            try:
                resp = await client.post("/v1/messages", json=payload)
                resp.raise_for_status()
                data = resp.json()
                # Parse response, emit a single DONE event with full text
                text_parts = []
                tool_calls = []
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "arguments": block.get("input", {}),
                        })
                full_text = "".join(text_parts)
                if full_text:
                    yield LLMEvent(kind="text", text=full_text)
                for tc in tool_calls:
                    yield LLMEvent(kind="tool_call", tool_call=tc)
                yield LLMEvent(
                    kind="done",
                    finish_reason=data.get("stop_reason", "end_turn"),
                )
            except httpx.HTTPError as e:
                log.exception("openclaw LLM call failed")
                yield LLMEvent(kind="error", error=str(e))
            return

        # Streaming path (SSE)
        try:
            async with client.stream("POST", "/v1/messages", json=payload) as resp:
                resp.raise_for_status()
                current_tool: dict | None = None
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    evt_type = event.get("type")
                    if evt_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool = {
                                "id": block.get("id"),
                                "name": block.get("name"),
                                "arguments": "",
                            }
                    elif evt_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield LLMEvent(kind="text", text=delta.get("text", ""))
                        elif delta.get("type") == "input_json_delta" and current_tool is not None:
                            current_tool["arguments"] += delta.get("partial_json", "")
                    elif evt_type == "content_block_stop":
                        if current_tool is not None:
                            try:
                                current_tool["arguments"] = json.loads(
                                    current_tool["arguments"] or "{}"
                                )
                            except json.JSONDecodeError:
                                current_tool["arguments"] = {}
                            yield LLMEvent(
                                kind="tool_call",
                                tool_call=dict(current_tool),
                            )
                            current_tool = None
                    elif evt_type == "message_stop":
                        yield LLMEvent(
                            kind="done",
                            finish_reason=event.get("message", {}).get("stop_reason"),
                        )
                    elif evt_type == "error":
                        yield LLMEvent(kind="error", error=event.get("error", {}).get("message"))
        except httpx.HTTPError as e:
            log.exception("openclaw LLM streaming failed")
            yield LLMEvent(kind="error", error=str(e))
