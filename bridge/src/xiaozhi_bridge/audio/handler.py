"""Audio handler: Opus decode + VAD + listen state machine (V2 #11c).

V2 #11c refactor: extracted from server.py 4 methods:
  - _handle_audio (66 lines)
  - _handle_listen (already in handle/textHandler/, kept thin)
  - _end_wake_grace (13 lines)
  - _cancel_wake_grace (22 lines)

The handle_listen extraction (V2 #11b) covers the listen state
machine; this module owns the audio-frame side (VAD + Opus +
buffering).
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..protocol import SessionState
from ..protocol.audio import make_codec


async def handle_audio(
    server: Any,
    ws: Any,
    session: Any,
    opus_frame: bytes,
) -> None:
    """Handle an incoming audio frame.

    V2 #8.3: with server-side VAD (Silero) integrated, we no
    longer rely on esp32's WebRTC VAD to trigger voice_stop. We:

      1. Decode Opus → PCM
      2. Run server-side VAD on the PCM
      3. Cache audio only when VAD says voice (or recent voice)
      4. When VAD detects voice_stop (1s silence), trigger
         _process_turn

    The VAD is opt-in: if server.vad is None (model missing),
    we fall back to the V2 #5 behavior of relying on
    listen.state=stop.
    """
    if session.state != SessionState.LISTENING:
        return

    # Decode Opus → PCM (reuse codec for the session — decoder
    # is stateful)
    codec = server._codecs.get(session.session_id)
    if codec is None:
        codec = make_codec(
            sample_rate=session.audio_params.sample_rate,
            channels=session.audio_params.channels,
            frame_duration_ms=session.audio_params.frame_duration,
        )
        server._codecs[session.session_id] = codec
    try:
        pcm = codec.decode(opus_frame)
    except Exception as e:
        server.log.warning(
            "audio.decode_failed", error=str(e), frame_size=len(opus_frame),
        )
        return

    # V2 #8.3: server-side VAD
    if server.vad is not None:
        have_voice = server.vad.is_vad(session, opus_frame)

        # Cache 10 frames even when no voice — captures sentence start
        if not have_voice and not session.client_have_voice:
            session.append_audio(pcm)
            # Keep only last ~10 frames worth of audio
            max_keep = 10 * len(pcm)
            if len(session.pcm_buffer) > max_keep:
                del session.pcm_buffer[: -max_keep]
            return

        session.append_audio(pcm)

        # voice_stop detected → trigger ASR pipeline
        if session.client_voice_stop:
            server.log.info(
                "vad.voice_stop",
                session_id=session.session_id,
                pcm_bytes=len(session.pcm_buffer),
            )
            # Reset VAD state BEFORE processing (so a new turn can start)
            server.vad.reset_session_state(session)
            await server._process_turn(ws, session)
    else:
        # No VAD: just buffer and rely on listen.state=stop
        session.append_audio(pcm)


async def end_wake_grace(server: Any, session: Any) -> None:
    """V2 #8.3: end the 2-second post-wake VAD grace period.

    Mirrors official xiaozhi-esp32-server: just_woken_up=True
    is set in _handle_listen(start), and reset 2s later to avoid
    false VAD positives from the wake word audio tail.
    """
    await asyncio.sleep(2.0)
    if hasattr(session, "just_woken_up"):
        session.just_woken_up = False
        server.log.info("vad.wake_grace_ended", session_id=session.session_id)


def cancel_wake_grace(server: Any, session: Any) -> None:
    """V2 #8.4: cancel the wake-grace task for a session.

    Called from session.closed cleanup to avoid tasks that
    reference a session after the session has been removed
    from server.sessions.
    """
    if not hasattr(server, "_wake_grace_tasks"):
        return
    session_id = session.session_id
    target_name = f"wake_grace_{session_id}"
    # Cancel all matching tasks
    for task in server._wake_grace_tasks:
        if task.get_name() == target_name and not task.done():
            task.cancel()
    # Remove the matching task by NAME (not by done state, since
    # task.cancel() doesn't immediately set done=True — the task
    # needs an event loop iteration to actually mark itself done).
    server._wake_grace_tasks = [
        t for t in server._wake_grace_tasks
        if t.get_name() != target_name and not t.done()
    ]
