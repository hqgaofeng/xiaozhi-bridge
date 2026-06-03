"""xiaozhi WebSocket protocol implementation.

Reference: ../../docs/protocol.md
"""

from .messages import (
    AudioParams,
    HelloFeatures,
    HelloMessage,
    ListenMessage,
    AbortMessage,
    MCPMessage,
    SystemMessage,
    STTMessage,
    LLMMessage,
    TTSMessage,
    ServerHello,
    # Factory
    parse_client_message,
    serialize_server_message,
)
from .states import SessionState, SessionContext
from .audio import OpusCodec

__all__ = [
    "AudioParams",
    "HelloFeatures",
    "HelloMessage",
    "ListenMessage",
    "AbortMessage",
    "MCPMessage",
    "SystemMessage",
    "STTMessage",
    "LLMMessage",
    "TTSMessage",
    "ServerHello",
    "parse_client_message",
    "serialize_server_message",
    "SessionState",
    "SessionContext",
    "OpusCodec",
]
