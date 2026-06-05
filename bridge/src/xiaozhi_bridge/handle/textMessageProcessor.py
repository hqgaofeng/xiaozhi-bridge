"""Message processor: dispatches parsed xiaozhi messages to handlers (V2 #11b).

V2 #11b refactor: replaces server.py's match-case in `_main_loop`
with a clean dispatch loop. The processor:

  1. Parses the raw WebSocket frame
  2. Looks up the handler by `msg.type`
  3. Calls `handler.handle(conn, ws, session, msg)`

Unknown message types are logged and dropped (same as the
V1 behavior of the `case _` branch).

Reference:
  78/xiaozhi-esp32-server main/xiaozhi-server/core/handle/
  textMessageProcessor.py — same shape.
"""

from __future__ import annotations

import json
from typing import Any

from .textMessageHandlerRegistry import TextMessageHandlerRegistry


class TextMessageProcessor:
    """Dispatch a parsed xiaozhi message to its registered handler."""

    def __init__(self, registry: TextMessageHandlerRegistry) -> None:
        self.registry = registry
        # Lazy-init: register defaults on first dispatch so tests
        # can inject mocks before the first message arrives.
        self._default_registered = False

    async def process_message(
        self,
        conn: Any,
        ws: Any,
        session: Any,
        raw: str,
    ) -> None:
        """Process one incoming JSON text message.

        Args:
            conn: XiaozhiBridgeServer (passed to handlers).
            ws: the WebSocket (passed to handlers).
            session: the per-connection session.
            raw: the raw JSON text frame.
        """
        if not self._default_registered:
            self.registry.register_default_handlers()
            self._default_registered = True

        # Parse (server already validated the frame is a text frame
        # in _main_loop; this is the JSON decode step).
        try:
            msg = self._parse(raw)
        except (ValueError, json.JSONDecodeError) as e:
            conn.log.warning("message.invalid", session_id=session.session_id, error=str(e))
            return

        # Look up handler.
        message_type = getattr(msg, "type", None) or msg.__class__.__name__
        handler = self.registry.get_handler(message_type)
        if handler is None:
            conn.log.warning(
                "message.unhandled",
                session_id=session.session_id,
                type=type(msg).__name__,
            )
            return

        # Dispatch.
        await handler.handle(conn, ws, session, msg)

    @staticmethod
    def _parse(raw: str) -> Any:
        """Parse a raw JSON string into a typed xiaozhi message.

        Mirrors the server.py's `parse_client_message` import
        but kept as a static method to allow tests to override.
        """
        # Lazy import — protocol/ imports types that handlers
        # also import; this is a cleaner top-level import.
        from ..protocol import parse_client_message
        return parse_client_message(raw)
