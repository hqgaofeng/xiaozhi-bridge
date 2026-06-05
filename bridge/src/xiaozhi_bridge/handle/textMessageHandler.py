"""Abstract base for xiaozhi text message handlers (V2 #11b).

V2 #11b refactor: split server.py's match-case dispatch into
per-message-type handler classes. The 78/xiaozhi-esp32-server
official reference uses the same pattern
(`core/handle/textHandler/*.py`), so this is a
"learn from upstream" change — not a novel design.

Each handler is responsible for ONE message type and is
dispatched by `TextMessageProcessor` via `TextMessageHandlerRegistry`.

Reference:
  78/xiaozhi-esp32-server main/xiaozhi-server/core/handle/
  textMessageHandler.py — same base class shape.
"""

from __future__ import annotations

import abc
from typing import Any


class TextMessageHandler(abc.ABC):
    """Abstract base for all xiaozhi text message handlers.

    Subclasses set `message_type` (the value of `msg.type` that
    triggers this handler) and implement `handle()`.
    """

    message_type: str  # subclass sets this to the protocol message type

    @abc.abstractmethod
    async def handle(
        self,
        conn: Any,  # XiaozhiBridgeServer (typed as Any to avoid circular)
        ws: Any,
        session: Any,  # SessionContext
        message: Any,  # the typed message (e.g. ListenMessage)
    ) -> None:
        """Process one message of this type.

        Args:
            conn: the server (for log, lifecycle, transitions).
            ws: the WebSocket (for sending responses).
            session: the per-connection session context.
            message: the typed message object.
        """
        raise NotImplementedError
