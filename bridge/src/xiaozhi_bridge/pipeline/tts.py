"""TTS pipeline (V2 #11c).

V2 #11c refactor: extracted from server.py `_send_tts`
(86 lines). Behavior preserved 1:1, including the V2 #8.4
ConnectionClosed graceful handling and the V2 #3 DB persistence
fallback.

TTS streaming protocol:
  1. tts.start                  (begin streaming)
  2. tts.sentence_start, text   (text displayed on device)
  3. Opus frames (N times)      (60ms frames @ 24kHz)
  4. tts.stop                   (end of stream)
"""

from __future__ import annotations

from typing import Any

import websockets

from ..protocol import SessionState, TTSMessage, serialize_server_message
from ..protocol.audio import OpusCodec, make_codec


async def send_tts(
    server: Any,
    ws: Any,
    session: Any,
    text: str,
) -> None:
    """Send TTS for the given text.

    Streams tts.start → tts.sentence_start → Opus frames →
    tts.stop. If the device disconnects mid-stream (V2 #8.4),
    we log at warning level (not exception) and let the caller
    persist the assistant turn to DB.

    Args:
        server: XiaozhiBridgeServer (for log + transitions).
        ws: the WebSocket (for sending TTS messages + audio).
        session: the per-connection session.
        text: the text to synthesize.
    """
    await server._transition(session, SessionState.SPEAKING)

    # TTS start
    await ws.send(serialize_server_message(
        TTSMessage(session_id=session.session_id, state="start")
    ))

    # Sentence start (text displayed on device)
    await ws.send(serialize_server_message(
        TTSMessage(
            session_id=session.session_id,
            state="sentence_start",
            text=text,
        )
    ))

    # TTS audio chunks
    try:
        tts_sr = 24000  # typical for xiaozhi playback
        tts_frame_ms = 60
        tts_codec = make_codec(
            sample_rate=tts_sr, channels=1, frame_duration_ms=tts_frame_ms
        )
        tts_frame_bytes = tts_sr * tts_frame_ms // 1000 * 2  # int16
        # If the codec is a real OpusCodec, encode PCM → Opus before sending.
        # PassThroughCodec (no libopus) just forwards bytes as-is.
        do_encode = isinstance(tts_codec, OpusCodec)

        pcm_buf = bytearray()
        async for chunk in server.tts.synthesize_stream(text, sample_rate=tts_sr):
            if not chunk.pcm:
                continue
            pcm_buf.extend(chunk.pcm)
            # Emit complete frames; keep any tail in the buffer.
            while len(pcm_buf) >= tts_frame_bytes:
                frame = bytes(pcm_buf[:tts_frame_bytes])
                del pcm_buf[:tts_frame_bytes]
                if do_encode:
                    frame = tts_codec.encode(frame)
                await ws.send(frame)
        # Flush any trailing PCM (pad with silence to a full frame).
        if pcm_buf:
            pad_samples = (tts_frame_bytes - len(pcm_buf)) // 2
            frame = bytes(pcm_buf) + b"\x00\x00" * pad_samples
            if do_encode:
                frame = tts_codec.encode(frame)
            await ws.send(frame)
    except Exception as e:
        # V2 #8.4: distinguish ConnectionClosed (esp32 gone) from
        # real TTS failures. esp32 often disconnects mid-TTS due to
        # keepalive timeout (LLM 19s thinking), and we don't want
        # the resulting ConnectionClosedError to pollute the log
        # as a "tts failure" — the TTS itself succeeded, the
        # transport just died.
        if isinstance(e, websockets.exceptions.ConnectionClosed):
            server.log.warning(
                "tts.client_disconnected",
                session_id=session.session_id,
                code=e.code,
                reason=str(e.reason) if e.reason else None,
            )
        else:
            server.log.exception("tts.failed")

    # TTS stop — also guarded: if the ws died mid-TTS, we just skip
    try:
        await ws.send(serialize_server_message(
            TTSMessage(session_id=session.session_id, state="stop")
        ))
    except websockets.exceptions.ConnectionClosed as e:
        server.log.warning(
            "tts.stop.client_disconnected",
            session_id=session.session_id,
            code=e.code,
        )
