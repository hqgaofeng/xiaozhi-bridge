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
