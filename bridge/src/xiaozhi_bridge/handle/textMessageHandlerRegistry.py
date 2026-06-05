"""Handler registry for xiaozhi text messages (V2 #11b).

V2 #11b refactor: replaces server.py's match-case dispatch
with a registry pattern. Adding a new message type = creating
an XxxTextMessageHandler + calling `register_handler`.

Reference:
  78/xiaozhi-esp32-server main/xiaozhi-server/core/handle/
  textMessageHandlerRegistry.py — same shape.
"""

from __future__ import annotations

from .textMessageHandler import TextMessageHandler


class TextMessageHandlerRegistry:
    """Message type → handler registry."""

    def __init__(self) -> None:
        self._handlers: dict[str, TextMessageHandler] = {}
        # Default handlers are registered lazily (at first dispatch)
        # by TextMessageProcessor — see `register_default_handlers`.
        self._default_registered: bool = False

    def register_handler(self, handler: TextMessageHandler) -> None:
        """Register a handler. Replaces any existing handler for the
        same message type (idempotent — useful for tests)."""
        self._handlers[handler.message_type] = handler

    def unregister_handler(self, message_type: str) -> bool:
        """Remove a handler. Returns True if removed, False if not registered."""
        return self._handlers.pop(message_type, None) is not None

    def get_handler(self, message_type: str) -> TextMessageHandler | None:
        """Look up a handler by message type. None if unknown."""
        return self._handlers.get(message_type)

    def get_supported_types(self) -> list[str]:
        """List of all registered message types (for debugging)."""
        return list(self._handlers.keys())

    def register_default_handlers(self) -> None:
        """Register the standard xiaozhi message handlers.

        Lazily imported to avoid a circular import (the handler
        modules import from protocol/, which imports from
        handle/ via __init__.py).
        """
        if self._default_registered:
            return
        # Lazy imports — see module docstring.
        from .textHandler.abortMessageHandler import AbortTextMessageHandler
        from .textHandler.helloMessageHandler import HelloTextMessageHandler
        from .textHandler.listenMessageHandler import ListenTextMessageHandler
        from .textHandler.mcpMessageHandler import McpTextMessageHandler

        for handler in (
            HelloTextMessageHandler(),
            ListenTextMessageHandler(),
            AbortTextMessageHandler(),
            McpTextMessageHandler(),
        ):
            self.register_handler(handler)
        self._default_registered = True


# Module-level default registry (per-process). The server's
# `_main_loop` uses this singleton; tests can create their
# own registry to inject mock handlers.
default_registry = TextMessageHandlerRegistry()
