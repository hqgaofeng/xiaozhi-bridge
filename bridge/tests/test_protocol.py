"""Tests for the xiaozhi protocol message parsing."""

import json
import pytest

from xiaozhi_bridge.protocol.messages import (
    HelloMessage,
    ListenMessage,
    AbortMessage,
    MCPMessage,
    ServerHello,
    parse_client_message,
    serialize_server_message,
    make_session_id,
)


def test_parse_hello():
    raw = json.dumps({
        "type": "hello",
        "version": 1,
        "features": {"mcp": True},
        "transport": "websocket",
        "audio_params": {
            "format": "opus",
            "sample_rate": 16000,
            "channels": 1,
            "frame_duration": 60,
        },
    })
    msg = parse_client_message(raw)
    assert isinstance(msg, HelloMessage)
    assert msg.features.mcp is True
    assert msg.audio_params.sample_rate == 16000


def test_parse_listen_start():
    raw = json.dumps({
        "session_id": "abc",
        "type": "listen",
        "state": "start",
        "mode": "auto",
    })
    msg = parse_client_message(raw)
    assert isinstance(msg, ListenMessage)
    assert msg.state == "start"
    assert msg.mode == "auto"


def test_parse_listen_detect():
    raw = json.dumps({
        "session_id": "abc",
        "type": "listen",
        "state": "detect",
        "text": "你好小智",
    })
    msg = parse_client_message(raw)
    assert isinstance(msg, ListenMessage)
    assert msg.state == "detect"
    assert msg.text == "你好小智"


def test_parse_abort():
    raw = json.dumps({
        "session_id": "abc",
        "type": "abort",
        "reason": "wake_word_detected",
    })
    msg = parse_client_message(raw)
    assert isinstance(msg, AbortMessage)
    assert msg.reason == "wake_word_detected"


def test_parse_mcp():
    raw = json.dumps({
        "session_id": "abc",
        "type": "mcp",
        "payload": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"cursor": ""},
        },
    })
    msg = parse_client_message(raw)
    assert isinstance(msg, MCPMessage)
    assert msg.payload["method"] == "tools/list"


def test_parse_missing_type():
    with pytest.raises(ValueError, match="Missing 'type'"):
        parse_client_message('{"foo": "bar"}')


def test_parse_unknown_type():
    with pytest.raises(ValueError, match="Unknown message type"):
        parse_client_message('{"type": "nonsense"}')


def test_serialize_server_hello():
    msg = ServerHello(
        session_id="abc",
        audio_params=__import__("xiaozhi_bridge.protocol.messages", fromlist=["AudioParams"]).AudioParams(),
    )
    out = serialize_server_message(msg)
    data = json.loads(out)
    assert data["type"] == "hello"
    assert data["session_id"] == "abc"


def test_session_id_format():
    sid = make_session_id()
    assert sid.startswith("xiaozhi-")
    assert len(sid) > len("xiaozhi-")
