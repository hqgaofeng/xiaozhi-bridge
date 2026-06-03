"""xiaozhi WebSocket message types.

Reference: ../../docs/protocol.md
All messages are JSON-encoded text frames except for audio (Opus binary).

Direction: C2S = client (device) → server, S2C = server → client.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal, Union

from pydantic import BaseModel, Field


# --- Audio params (shared) ---


class AudioParams(BaseModel):
    """Audio codec parameters.

    Default is 16 kHz Opus mono, 60 ms frames — what xiaozhi-esp32 sends.
    Server can negotiate 24 kHz for TTS playback.
    """

    format: Literal["opus"] = "opus"
    sample_rate: int = 16000
    channels: int = 1
    frame_duration: int = 60


class HelloFeatures(BaseModel):
    """Optional features advertised in the hello message."""

    mcp: bool = False


# --- C2S: Client → Server messages ---


class HelloMessage(BaseModel):
    """C2S: Initial handshake from device."""

    type: Literal["hello"] = "hello"
    version: int = 1
    features: HelloFeatures = Field(default_factory=HelloFeatures)
    transport: Literal["websocket"] = "websocket"
    audio_params: AudioParams = Field(default_factory=AudioParams)


class ListenMessage(BaseModel):
    """C2S: Listen state notification.

    - state=start: device is recording, will send Opus binary frames
    - state=stop: device stopped recording, server should finalize ASR
    - state=detect: wake word detected, may include the text
    """

    session_id: str
    type: Literal["listen"] = "listen"
    state: Literal["start", "stop", "detect"]
    mode: Literal["auto", "manual", "realtime"] | None = None
    text: str | None = None  # Only for state=detect


class AbortMessage(BaseModel):
    """C2S: Abort current TTS playback or session."""

    session_id: str
    type: Literal["abort"] = "abort"
    reason: str | None = None  # e.g. "wake_word_detected"


class MCPMessage(BaseModel):
    """C2S: MCP JSON-RPC 2.0 message from device.

    The payload is a JSON-RPC 2.0 request/response/notification.
    """

    session_id: str
    type: Literal["mcp"] = "mcp"
    payload: dict[str, Any]


# --- S2C: Server → Client messages ---


class ServerHello(BaseModel):
    """S2C: Handshake response from server."""

    type: Literal["hello"] = "hello"
    transport: Literal["websocket"] = "websocket"
    session_id: str
    audio_params: AudioParams = Field(default_factory=AudioParams)


class STTMessage(BaseModel):
    """S2C: Speech-to-text result."""

    session_id: str
    type: Literal["stt"] = "stt"
    text: str


class LLMMessage(BaseModel):
    """S2C: LLM emotion/text expression.

    Sent alongside TTS to give the device an animation/emotion cue.
    """

    session_id: str
    type: Literal["llm"] = "llm"
    emotion: str = "neutral"  # happy | sad | angry | neutral | ...
    text: str = ""  # usually an emoji or short symbol


class TTSMessage(BaseModel):
    """S2C: TTS state notification.

    State machine:
      start → (sentence_start, text) → (binary Opus frames) → ... → stop
    """

    session_id: str
    type: Literal["tts"] = "tts"
    state: Literal["start", "stop", "sentence_start"]
    text: str | None = None  # Only for state=sentence_start


class SystemMessage(BaseModel):
    """S2C: System command (e.g. reboot)."""

    session_id: str
    type: Literal["system"] = "system"
    command: str


# --- Discriminated union of all client messages ---


ClientMessage = Union[HelloMessage, ListenMessage, AbortMessage, MCPMessage]

# All server messages (for serialization)
ServerMessage = Union[
    ServerHello, STTMessage, LLMMessage, TTSMessage, MCPMessage, SystemMessage
]


# --- Parse / serialize helpers ---


def parse_client_message(raw: str | bytes) -> ClientMessage:
    """Parse a JSON text frame from the device.

    Raises ValueError if `type` is missing or unknown.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    msg_type = data.get("type")
    if not msg_type:
        raise ValueError(f"Missing 'type' field: {raw[:200]}")

    match msg_type:
        case "hello":
            return HelloMessage(**data)
        case "listen":
            return ListenMessage(**data)
        case "abort":
            return AbortMessage(**data)
        case "mcp":
            return MCPMessage(**data)
        case _:
            raise ValueError(f"Unknown message type: {msg_type}")


def serialize_server_message(msg: ServerMessage) -> str:
    """Serialize a server message to JSON text frame."""
    return msg.model_dump_json(exclude_none=True)


def make_session_id(prefix: str = "xiaozhi") -> str:
    """Generate a new session ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
