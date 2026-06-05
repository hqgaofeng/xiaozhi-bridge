"""Hello message handler (V2 #11b).

In the V2 protocol, the client sends `type: "hello"` ONCE
during the handshake. Subsequent hello messages are
unexpected (V2 #6.1: re-handshake is forbidden — the device
should reconnect instead). This handler is defensive: it
logs and ignores them.
"""

from __future__ import annotations

from typing import Any

from ...protocol import HelloMessage
from ..textMessageHandler import TextMessageHandler


class HelloTextMessageHandler(TextMessageHandler):
    """Handle unexpected hello messages mid-connection.

    The initial hello is processed in `server._handle_connection`
    (before the main loop starts), so any hello that reaches
    this handler is a duplicate — we log and drop.
    """

    message_type = "hello"

    async def handle(
        self,
        conn: Any,
        ws: Any,
        session: Any,
        message: HelloMessage,
    ) -> None:
        conn.log.warning(
            "message.unexpected_hello",
            session_id=session.session_id,
        )
