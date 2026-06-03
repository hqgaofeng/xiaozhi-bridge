"""OpenClaw LLM client.

Calls the openclaw gateway's OpenAI-compatible /v1/chat/completions endpoint.
The gateway is treated as an **agent target** (not a raw model): tool calling,
session memory, and tool dispatch (web_search, etc.) all happen inside openclaw.
The bridge only consumes streamed text content and forwards it to TTS.

Key facts (verified against openclaw 2026.5.28 dist code):
- The endpoint is disabled by default; must be enabled via
  `gateway.http.endpoints.chatCompletions.enabled: true` in openclaw.json.
- Auth: `Authorization: Bearer <gateway.auth.token>` (gateway.auth.mode=token).
- Model field is an agent target, not a provider model id:
  - `model: "openclaw"` → default agent
  - `model: "openclaw/<agentId>"` → specific agent (e.g. `openclaw/main`)
  - `x-openclaw-model: <provider/model>` header overrides the backend LLM.
- Session isolation: a stable `user` field (or `x-openclaw-session-key` header)
  gives every call a deterministic sessionKey; without it, the gateway
  generates a fresh UUID per call (stateless).
- External `tools[]` are rejected with `invalid tool configuration` — openclaw
  uses its own tool registry. Don't send them.

Reference: ../../docs/architecture.md (LLM section),
  openclaw docs /gateway/openai-http-api.md.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import LLMClient, LLMEvent, Message, register_llm

log = logging.getLogger(__name__)


@register_llm("openclaw")
class OpenClawLLM(LLMClient):
    """LLM client that calls the openclaw gateway's chat-completions API.

    Streaming only. Yields TEXT events (incremental content) and a final DONE.
    Tool calls happen inside openclaw and do not surface here.
    """

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(options)
        self.base_url = self.options.get("base_url", "http://127.0.0.1:18789").rstrip("/")
        self.api_key = self.options.get("api_key", "")
        # `model` is an agent target, not a raw provider model id.
        # Default: route to the default agent.
        self.model = self.options.get("model", "openclaw")
        # Optional backend-model override header (e.g. "minimax/MiniMax-M3-highspeed").
        self.backend_model = self.options.get("backend_model", "")
        # Stable per-caller session id; openclaw derives a deterministic
        # sessionKey from this and keeps history separate from other callers.
        self.user = self.options.get("user", "xiaozhi-bridge")
        # Optional explicit session key (overrides `user` if both set).
        self.session_key = self.options.get("session_key", "")
        self.max_tokens = int(self.options.get("max_tokens", 4096))
        self.temperature = float(self.options.get("temperature", 0.7))
        self.timeout = float(self.options.get("timeout", 60.0))

        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
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
        # `tools` and `system` are accepted for interface compatibility
        # with LLMClient.chat_stream but intentionally IGNORED — openclaw
        # owns tool dispatch and system prompts (per-agent / per-session).
        tools: list | None = None,
        system: str | None = None,
    ) -> dict:
        api_messages: list[dict] = []
        for msg in messages:
            # Bridge never sends role=tool or role=system through this client
            # (openclaw handles those internally), but be defensive.
            if msg.role in ("system", "tool"):
                continue
            api_messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
            "user": self.user,
            "messages": api_messages,
        }
        if self.session_key:
            payload["user"] = self.session_key  # `user` wins; session_key only via header
        return payload

    def _extra_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.session_key:
            h["x-openclaw-session-key"] = self.session_key
        if self.backend_model:
            h["x-openclaw-model"] = self.backend_model
        return h

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list | None = None,
        system: str | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """Stream chat completion from openclaw.

        Only TEXT and DONE events are emitted. Tool calls (if any) happen
        inside openclaw and never appear in the stream.
        """
        client = await self._get_client()
        payload = self._build_payload(messages, tools, system)
        headers = self._extra_headers()

        try:
            async with client.stream(
                "POST", "/v1/chat/completions", json=payload, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    err = body.decode("utf-8", errors="replace")
                    log.error("openclaw.chat.error", status=resp.status_code, body=err[:500])
                    yield LLMEvent(
                        kind="error",
                        error=f"openclaw HTTP {resp.status_code}: {err[:200]}",
                    )
                    return
                finish_reason: str | None = None
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            yield LLMEvent(kind="done", finish_reason=finish_reason or "stop")
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    # OpenAI chat.completion.chunk shape:
                    # {choices: [{delta: {content?: str, role?: str}, finish_reason?: str}]}
                    for choice in event.get("choices", []):
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield LLMEvent(kind="text", text=content)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                    # OpenClaw may emit a top-level error chunk
                    if "error" in event:
                        yield LLMEvent(
                            kind="error",
                            error=str(event["error"].get("message", event["error"])),
                        )
                        return
        except httpx.HTTPError as e:
            log.exception("openclaw.chat.stream_failed")
            yield LLMEvent(kind="error", error=str(e))
