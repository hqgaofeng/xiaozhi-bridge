"""Device session state machine.

Each connected device has one SessionContext that tracks:
- Current state (idle, listening, thinking, speaking)
- Audio buffers
- Session metadata
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .messages import (
    AudioParams,
    HelloMessage,
    make_session_id,
)


class SessionState(StrEnum):
    """Top-level device session states.

    State diagram:

        idle ──listen start──> listening ──tts start──> speaking
         ▲                        │                        │
         │                        └─abort──────────────────┤
         │                                                   │
         └────────────────tts stop──────────────────────────┘
    """

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"  # server is processing
    SPEAKING = "speaking"  # server is sending TTS audio


@dataclass
class SessionContext:
    """Per-device session context.

    One instance per WebSocket connection. Not thread-safe — only access
    from the asyncio task that owns the connection.
    """

    session_id: str
    device_id: str | None = None
    client_id: str | None = None
    state: SessionState = SessionState.IDLE
    audio_params: AudioParams = field(default_factory=AudioParams)

    # Audio buffer for current turn (PCM bytes after Opus decode)
    pcm_buffer: bytearray = field(default_factory=bytearray)

    # Timing
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)

    # Current turn text (filled by ASR, consumed by LLM)
    current_text: str = ""
    current_turn_id: int = 0

    # Optional metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_hello(cls, hello: HelloMessage, device_id: str | None = None) -> SessionContext:
        """Create a new session from a hello message."""
        return cls(
            session_id=make_session_id(),
            device_id=device_id,
            audio_params=hello.audio_params,
        )

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity_at = time.time()

    def is_idle(self) -> bool:
        return self.state == SessionState.IDLE

    def is_busy(self) -> bool:
        """Device is busy if not idle (audio playing or thinking)."""
        return self.state != SessionState.IDLE

    def transition(self, new_state: SessionState) -> None:
        """Transition to a new state with logging."""
        old = self.state
        self.state = new_state
        self.touch()
        # Logger is set up in main; import here to avoid circular
        import structlog
        log = structlog.get_logger()
        log.info(
            "session.state_transition",
            session_id=self.session_id,
            from_state=old.value,
            to_state=new_state.value,
        )

    async def persist_state(self, db) -> None:
        """V2 #3: write last_state to the bridge db. Best-effort.

        The db argument is a BridgeDB (or any object with
        update_session_state()); we accept untyped to avoid a
        circular import between states.py and api.db.
        """
        if db is None:
            return
        import contextlib
        with contextlib.suppress(Exception):
            # Persistence failure must not break the turn
            await db.update_session_state(self.session_id, self.state.value)

    def append_audio(self, pcm: bytes) -> None:
        """Append PCM audio to the current turn's buffer."""
        self.pcm_buffer.extend(pcm)
        self.touch()

    def clear_audio(self) -> bytes:
        """Return the buffered audio and clear the buffer."""
        buf = bytes(self.pcm_buffer)
        self.pcm_buffer.clear()
        return buf
