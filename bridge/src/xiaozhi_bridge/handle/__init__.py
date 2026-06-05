"""Handle package: text message dispatch via registry pattern (V2 #11b).

V2 #11b refactor: replaces server.py's match-case in `_main_loop`
with a per-message-type handler dispatch system. Mirrors the
78/xiaozhi-esp32-server official design.

Layout:
  textMessageHandler.py        # abstract base
  textMessageHandlerRegistry.py # type → handler map
  textMessageProcessor.py       # dispatches one message
  textHandler/                  # concrete handlers
    __init__.py
    helloMessageHandler.py     # server_hello handshake
    listenMessageHandler.py    # listen state machine
    abortMessageHandler.py     # abort
    mcpMessageHandler.py       # MCP JSON-RPC routing
"""

from .textMessageHandler import TextMessageHandler
from .textMessageHandlerRegistry import (
    TextMessageHandlerRegistry,
    default_registry,
)
from .textMessageProcessor import TextMessageProcessor

__all__ = [
    "TextMessageHandler",
    "TextMessageHandlerRegistry",
    "TextMessageProcessor",
    "default_registry",
]
