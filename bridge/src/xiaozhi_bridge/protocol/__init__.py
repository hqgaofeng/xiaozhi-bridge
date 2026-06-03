"""xiaozhi WebSocket protocol implementation.

Reference: ../../docs/protocol.md
"""

from .audio import OpusCodec
from .messages import (
    AbortMessage,
    AudioParams,
    HelloFeatures,
    HelloMessage,
    ListenMessage,
    LLMMessage,
    MCPMessage,
    ServerHello,
    STTMessage,
    SystemMessage,
    TTSMessage,
    # Factory
    parse_client_message,
    serialize_server_message,
)
from .states import SessionContext, SessionState

__all__ = [
    "AbortMessage",
    "AudioParams",
    "HelloFeatures",
    "HelloMessage",
    "LLMMessage",
    "ListenMessage",
    "MCPMessage",
    "OpusCodec",
    "STTMessage",
    "ServerHello",
    "SessionContext",
    "SessionState",
    "SystemMessage",
    "TTSMessage",
    "parse_client_message",
    "serialize_server_message",
]
