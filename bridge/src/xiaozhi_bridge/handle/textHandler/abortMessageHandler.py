"""Abort message handler (V2 #11b)."""

from __future__ import annotations

from typing import Any

from ...protocol import AbortMessage, SessionState
from ..textMessageHandler import TextMessageHandler


class AbortTextMessageHandler(TextMessageHandler):
    """Handle `type: "abort"` messages from the device.

    The current behavior (V2 #7): transition to IDLE and log.
    V2 #7.10 TBD: cancel any in-flight LLM/TTS — kept as
    a TODO for now since the v0.2.x LLM is fast enough that
    aborts are rare.
    """

    message_type = "abort"

    async def handle(
        self,
        conn: Any,
        ws: Any,
        session: Any,
        message: AbortMessage,
    ) -> None:
        conn.log.info("abort.received", session_id=session.session_id, reason=message.reason)
        await conn._transition(session, SessionState.IDLE)
        # TBD: cancel any in-flight LLM/TTS
