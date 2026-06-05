"""Listen message handler (V2 #11b).

V2 #11b refactor: extracted from server.py `_handle_listen`
(41 lines) into a standalone handler. The behavior is
preserved 1:1 — the only change is the dispatch path (match-case
→ registry).

Listen state machine (V2 #8.3):
  start   → LISTENING state, reset VAD, start 2s wake-grace
  stop    → _process_turn (ASR → LLM → TTS)
  detect  → _process_text (skip ASR, just LLM with the hint text)
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...protocol import ListenMessage, SessionState
from ..textMessageHandler import TextMessageHandler


class ListenTextMessageHandler(TextMessageHandler):
    """Handle `type: "listen"` messages from the device."""

    message_type = "listen"

    async def handle(
        self,
        conn: Any,
        ws: Any,
        session: Any,
        message: ListenMessage,
    ) -> None:
        session.touch()
        conn.log.info(
            "listen.event",
            session_id=session.session_id,
            state=message.state,
            mode=message.mode,
            text=message.text,
        )

        if message.state == "start":
            await conn._transition(session, SessionState.LISTENING)
            session.pcm_buffer.clear()
            # V2 #8.3: reset VAD state and start wake-up grace
            # period (mirrors official xiaozhi-esp32-server:
            # ignore VAD for 2s after wake word to avoid false
            # positive from wake word tail).
            if conn.vad is not None:
                conn.vad.reset_session_state(session)
                session.just_woken_up = True
                if not hasattr(conn, "_wake_grace_tasks"):
                    conn._wake_grace_tasks = []
                task = asyncio.create_task(
                    conn._end_wake_grace(session),
                    name=f"wake_grace_{session.session_id}",
                )
                conn._wake_grace_tasks.append(task)
        elif message.state == "stop":
            # User stopped recording → run ASR → LLM → TTS pipeline
            await conn._process_turn(ws, session)
        elif message.state == "detect":
            # Wake word detected (with text hint) → just process
            # the text directly
            if message.text:
                await conn._process_text(ws, session, message.text)
