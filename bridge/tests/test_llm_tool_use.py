"""Tests for V2 #7 LLM tool_use event handling (openclaw.py)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xiaozhi_bridge.llm.base import Message
from xiaozhi_bridge.llm.openclaw import OpenClawLLM


def _sse_line(data: str) -> bytes:
    return f"data: {data}\n\n".encode()


@pytest.mark.asyncio
async def test_openclaw_yields_tool_call_event():
    """V2 #7: when the LLM emits a tool_calls finish_reason,
    we yield exactly one TOOL_CALL event per accumulated tool call."""

    # Build a fake openclaw response with a tool_calls delta.
    chunks = [
        # chunk 1: tool name starts
        json.dumps({
            "choices": [{
                "delta": {
                    "role": "assistant",
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "self.audio_speaker.set_"},
                    }],
                },
            }],
        }),
        # chunk 2: tool name finishes
        json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"name": "volume"},
                    }],
                },
            }],
        }),
        # chunk 3: arguments start
        json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": '{"volum'},
                    }],
                },
            }],
        }),
        # chunk 4: arguments finish + finish_reason
        json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": 'e": 50}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }),
    ]

    # Set up mock httpx stream
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    mock_resp.aiter_lines = MagicMock()

    async def gen_lines():
        for chunk in chunks:
            yield f"data: {chunk}"
        yield "data: [DONE]"

    mock_resp.aiter_lines = MagicMock(return_value=gen_lines())

    client = OpenClawLLM(options={
        "base_url": "http://fake",
        "api_key": "fake-key",
        "user": "test",
    })

    # Patch the httpx.AsyncClient.stream call.
    with patch("httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_async_client.return_value)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.return_value.stream.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_async_client.return_value.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        events = []
        async for event in client.chat_stream(messages=[Message(role="user", content="调小音量")]):
            events.append(event)

    # Find the TOOL_CALL event
    tool_events = [e for e in events if e.kind == "tool_call"]
    assert len(tool_events) == 1, f"expected 1 tool_call event, got {len(tool_events)}"
    assert tool_events[0].tool_call["name"] == "self.audio_speaker.set_volume"
    assert tool_events[0].tool_call["arguments"] == {"volume": 50}
    assert tool_events[0].tool_call["id"] == "call_1"


def test_openclaw_passes_tools_in_payload():
    """V2 #7: tools list is forwarded to openclaw (not IGNORED anymore)."""
    client = OpenClawLLM(options={"base_url": "http://fake", "user": "test"})
    tools = [
        {
            "type": "function",
            "function": {
                "name": "self.audio_speaker.set_volume",
                "description": "Set volume",
                "parameters": {"type": "object", "properties": {"volume": {"type": "integer"}}},
            },
        },
    ]
    payload = client._build_payload(
        messages=[Message(role="user", content="hi")],
        tools=tools,
    )
    assert "tools" in payload
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"


def test_openclaw_omits_tools_when_empty():
    """V2 #7: if no tools provided, don't add tools=[] (avoids
    surprising openclaw with an empty tools list)."""
    client = OpenClawLLM(options={"base_url": "http://fake", "user": "test"})
    payload = client._build_payload(
        messages=[Message(role="user", content="hi")],
        tools=None,
    )
    assert "tools" not in payload
    assert "tool_choice" not in payload


# --- V2 #7 bug fix: tool_calls + tool_call_id forwarded in payload ---


def test_build_payload_forwards_assistant_tool_calls():
    """V2 #7: assistant tool_calls turn MUST include tool_calls array.

    Without this, openclaw treats the assistant turn as pure text and
    drops the subsequent tool result. V1 was buggy (only sent
    role+content).
    """
    client = OpenClawLLM(options={"base_url": "http://fake", "user": "test"})
    messages = [
        Message(role="user", content="调音量到 50"),
        Message(
            role="assistant",
            content="",
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "set_volume", "arguments": '{"volume": 50}'},
            }],
        ),
    ]
    payload = client._build_payload(messages=messages)
    assistant_turn = next(
        m for m in payload["messages"] if m["role"] == "assistant"
    )
    assert "tool_calls" in assistant_turn
    assert assistant_turn["tool_calls"][0]["id"] == "call_1"
    assert assistant_turn["tool_calls"][0]["function"]["name"] == "set_volume"


def test_build_payload_forwards_tool_call_id():
    """V2 #7: tool result turn MUST include tool_call_id.

    Without this, the LLM can't associate the result with the
    tool_call it answers, leading to 'no tool_call found' errors
    on multi-tool turns.
    """
    client = OpenClawLLM(options={"base_url": "http://fake", "user": "test"})
    messages = [
        Message(role="tool", content="ok", tool_call_id="call_xyz", name="set_volume"),
    ]
    payload = client._build_payload(messages=messages)
    tool_turn = payload["messages"][0]
    assert tool_turn["tool_call_id"] == "call_xyz"
    assert tool_turn["name"] == "set_volume"


def test_build_payload_skips_tool_call_id_when_absent():
    """V2 #7: tool result without tool_call_id is still allowed
    (e.g. legacy FunctionTool results that don't carry the field)."""
    client = OpenClawLLM(options={"base_url": "http://fake", "user": "test"})
    messages = [Message(role="tool", content="ok")]  # no tool_call_id
    payload = client._build_payload(messages=messages)
    tool_turn = payload["messages"][0]
    assert "tool_call_id" not in tool_turn


# --- V2 #7 bug fix: tool id is single, not concatenated ---


@pytest.mark.asyncio
async def test_openclaw_tool_id_not_concatenated():
    """V2 #7 bug fix: tool call id is a single value, not a stream delta.

    The OpenAI API sends the id on the first chunk and never again
    for the same tool call. Previously we did `slot['id'] += delta`
    which would duplicate the id on every chunk where it appeared.
    """
    chunks = [
        # chunk 1: id + name + first arg
        json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "set_", "arguments": '{"v'},
                    }],
                },
            }],
        }),
        # chunk 2: name + more args (no id)
        json.dumps({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"name": "volume", "arguments": 'olume": 50}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }),
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    async def gen_lines():
        for chunk in chunks:
            yield f"data: {chunk}"
        yield "data: [DONE]"

    mock_resp.aiter_lines = MagicMock(return_value=gen_lines())

    client = OpenClawLLM(options={"base_url": "http://fake", "user": "test"})

    with patch("httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_async_client.return_value)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.return_value.stream.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_async_client.return_value.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        events = []
        async for event in client.chat_stream(messages=[Message(role="user", content="hi")]):
            events.append(event)

    tool_events = [e for e in events if e.kind == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_call["id"] == "call_abc", (
        f"id should be 'call_abc' (not 'call_abccall_abc' from concatenation), "
        f"got {tool_events[0].tool_call['id']!r}"
    )
    assert tool_events[0].tool_call["name"] == "set_volume"
    assert tool_events[0].tool_call["arguments"] == {"volume": 50}
