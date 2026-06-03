"""WebSocket server for xiaozhi-esp32 devices.

This is the heart of the bridge:
- Accepts WebSocket connections from devices
- Parses xiaozhi protocol messages
- Orchestrates ASR → LLM → TTS pipeline
- Forwards MCP JSON-RPC messages

Each connection runs an independent asyncio task with its own SessionContext.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import websockets
from websockets.legacy.server import WebSocketServerProtocol

from .asr import get_asr
from .config import AppConfig
from .llm import get_llm
from .llm.base import Message as LLMMessage_
from .mcp import MCPServer
from .protocol import (
    AbortMessage,
    HelloMessage,
    ListenMessage,
    LLMMessage,
    MCPMessage,
    ServerHello,
    SessionContext,
    SessionState,
    STTMessage,
    TTSMessage,
    parse_client_message,
    serialize_server_message,
)
from .protocol.audio import make_codec
from .tts import get_tts

log = logging.getLogger(__name__)


# --- Main server class ---


def _get_header(ws: WebSocketServerProtocol, name: str, default: str | None = None) -> str | None:
    """Read a header from a WebSocket connection, supporting both
    websockets.legacy (ws.request_headers) and websockets ≥14 (ws.handshake.headers).
    """
    # Legacy API (websockets < 14, used by pyproject's loose dep)
    if hasattr(ws, "request_headers"):
        return ws.request_headers.get(name, default)
    # New API
    hs = getattr(ws, "handshake", None)
    if hs is not None and getattr(hs, "headers", None) is not None:
        # websockets.http.Headers is a dict-like with .get
        return hs.headers.get(name, default)
    return default



class XiaozhiBridgeServer:
    """WebSocket server that handles xiaozhi-esp32 devices."""

    def __init__(self, config: AppConfig):
        self.config = config
        # Use structlog to match the structured `info("event", key=value)`
        # call sites used throughout this module.
        from .utils.logging import get_logger
        self.log = get_logger(self.__class__.__name__)

        # Initialize components
        self.asr = get_asr(config.asr.provider, config.asr.options)
        self.tts = get_tts(config.tts.provider, config.tts.options)
        self.llm = get_llm("openclaw", config.openclaw.model_dump())
        self.mcp = MCPServer()

        # Track active sessions
        self.sessions: dict[str, SessionContext] = {}

        # Cache audio codecs per session (Opus decoder is stateful)
        self._codecs: dict[str, Any] = {}

        # WebSocket server
        self._server: Any = None

    async def start(self) -> None:
        """Start the WebSocket server."""
        self.log.info(
            "server.starting",
            host=self.config.server.host,
            port=self.config.server.port,
            path=self.config.server.path,
        )

        # Path filter — reject WebSocket upgrades to other paths
        target_path = self.config.server.path

        def _process_request(connection, request):
            """Reject WS upgrades that don't match the configured path."""
            if request.path != target_path:
                self.log.warning(
                    "ws.path_mismatch",
                    expected=target_path,
                    got=request.path,
                )
                return connection.respond(404, "Not Found")
            return None  # proceed with WS handshake

        self._server = await websockets.serve(
            self._handle_connection,
            self.config.server.host,
            self.config.server.port,
            max_size=self.config.server.max_message_size,
            process_request=_process_request,
        )
        self.log.info("server.started", url=f"ws://{self.config.server.host}:{self.config.server.port}{target_path}")

    async def stop(self) -> None:
        """Stop the WebSocket server gracefully."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        await self.llm.close()
        self.log.info("server.stopped")

    async def serve_forever(self) -> None:
        """Block forever serving connections."""
        if self._server:
            await self._server.wait_closed()

    # --- Connection handler ---

    async def _handle_connection(
        self,
        ws: WebSocketServerProtocol,
    ) -> None:
        """Handle one device WebSocket connection.

        Lifecycle:
        1. Receive hello → send server hello → create session
        2. Loop: receive messages / audio, dispatch to handlers
        3. On disconnect: cleanup
        """
        peer = f"{ws.remote_address[0]}:{ws.remote_address[1]}" if ws.remote_address else "?"
        self.log.info("connection.opened", peer=peer)

        session: SessionContext | None = None

        try:
            # Phase 1: handshake — first message must be hello
            first = await ws.recv()
            if isinstance(first, bytes):
                # Audio before hello is invalid
                await ws.close(code=1008, reason="expected hello message")
                return

            try:
                msg = parse_client_message(first)
            except (ValueError, json.JSONDecodeError) as e:
                self.log.warning("handshake.invalid", peer=peer, error=str(e))
                await ws.close(code=1008, reason="invalid hello")
                return

            if not isinstance(msg, HelloMessage):
                self.log.warning("handshake.expected_hello", got=msg.type)
                await ws.close(code=1008, reason="expected hello")
                return

            # Optional auth check
            if self.config.device.auth_token:
                auth = _get_header(ws, "Authorization", "")
                expected = f"Bearer {self.config.device.auth_token}"
                if auth != expected:
                    self.log.warning("handshake.unauthorized", peer=peer)
                    await ws.close(code=1001, reason="unauthorized")
                    return

            # Get device id from header
            device_id = _get_header(ws, "Device-Id")

            # Create session
            session = SessionContext.from_hello(msg, device_id=device_id)
            self.sessions[session.session_id] = session
            self.log.info(
                "session.created",
                session_id=session.session_id,
                device_id=device_id,
            )

            # Send server hello
            server_hello = ServerHello(
                session_id=session.session_id,
                audio_params=msg.audio_params,
            )
            await ws.send(serialize_server_message(server_hello))

            # Phase 2: main loop
            await self._main_loop(ws, session)

        except websockets.ConnectionClosed as e:
            self.log.info("connection.closed", peer=peer, code=e.code, reason=e.reason)
        except Exception:
            self.log.exception("connection.error", peer=peer)
        finally:
            if session:
                self.sessions.pop(session.session_id, None)
                # Clean up cached codec
                self._codecs.pop(session.session_id, None)
                self.log.info("session.closed", session_id=session.session_id)

    async def _main_loop(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
    ) -> None:
        """Main message loop for a connected device."""
        async for raw in ws:
            if isinstance(raw, bytes):
                # Audio frame (Opus)
                await self._handle_audio(ws, session, raw)
            else:
                # JSON text frame
                try:
                    msg = parse_client_message(raw)
                except (ValueError, json.JSONDecodeError) as e:
                    self.log.warning("message.invalid", session_id=session.session_id, error=str(e))
                    continue

                match msg:
                    case ListenMessage():
                        await self._handle_listen(ws, session, msg)
                    case AbortMessage():
                        await self._handle_abort(ws, session, msg)
                    case MCPMessage():
                        await self._handle_mcp(ws, session, msg)
                    case HelloMessage():
                        self.log.warning("message.unexpected_hello", session_id=session.session_id)
                    case _:
                        self.log.warning("message.unhandled", type=type(msg).__name__)

    # --- Message handlers ---

    async def _handle_audio(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        opus_frame: bytes,
    ) -> None:
        """Handle an incoming audio frame.

        Only act when in LISTENING state — otherwise we just buffer/ignore.
        For V1 we just count frames; real ASR will be added in a later step.
        """
        if session.state != SessionState.LISTENING:
            return

        # Decode Opus → PCM (reuse codec for the session — decoder is stateful)
        codec = self._codecs.get(session.session_id)
        if codec is None:
            codec = make_codec(
                sample_rate=session.audio_params.sample_rate,
                channels=session.audio_params.channels,
                frame_duration_ms=session.audio_params.frame_duration,
            )
            self._codecs[session.session_id] = codec
        try:
            pcm = codec.decode(opus_frame)
            session.append_audio(pcm)
        except Exception as e:
            self.log.warning("audio.decode_failed", error=str(e))

    async def _handle_listen(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        msg: ListenMessage,
    ) -> None:
        """Handle listen state changes."""
        session.touch()
        self.log.info(
            "listen.event",
            session_id=session.session_id,
            state=msg.state,
            mode=msg.mode,
            text=msg.text,
        )

        if msg.state == "start":
            session.transition(SessionState.LISTENING)
            session.pcm_buffer.clear()
        elif msg.state == "stop":
            # User stopped recording → run ASR → LLM → TTS pipeline
            await self._process_turn(ws, session)
        elif msg.state == "detect":
            # Wake word detected (with text hint) → just process the text directly
            if msg.text:
                await self._process_text(ws, session, msg.text)

    async def _handle_abort(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        msg: AbortMessage,
    ) -> None:
        """Handle abort."""
        self.log.info("abort.received", session_id=session.session_id, reason=msg.reason)
        session.transition(SessionState.IDLE)
        # TBD: cancel any in-flight LLM/TTS

    async def _handle_mcp(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        msg: MCPMessage,
    ) -> None:
        """Handle MCP JSON-RPC 2.0 message from device."""
        self.log.info("mcp.received", session_id=session.session_id)
        response = await self.mcp.handle(msg.payload)
        if response is not None:
            await ws.send(serialize_server_message(
                MCPMessage(session_id=session.session_id, payload=response)
            ))

    # --- Pipeline ---

    async def _process_turn(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
    ) -> None:
        """Process one turn: ASR → LLM → TTS.

        Called when the device sends listen=stop (end of recording).
        """
        pcm = session.clear_audio()
        if not pcm:
            self.log.info("turn.empty_audio", session_id=session.session_id)
            session.transition(SessionState.IDLE)
            return

        session.transition(SessionState.THINKING)

        # 1) ASR: PCM → text
        try:
            asr_result = await self.asr.transcribe(
                pcm,
                sample_rate=session.audio_params.sample_rate,
                channels=session.audio_params.channels,
            )
        except Exception:
            self.log.exception("asr.failed")
            await self._send_tts(ws, session, "抱歉，我没听清楚。")
            session.transition(SessionState.IDLE)
            return

        text = asr_result.text.strip()
        if not text:
            session.transition(SessionState.IDLE)
            return

        # Send STT result to device (so it can show on screen)
        await ws.send(serialize_server_message(
            STTMessage(session_id=session.session_id, text=text)
        ))

        # 2) LLM + 3) TTS
        await self._process_text(ws, session, text)

    async def _process_text(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        text: str,
    ) -> None:
        """Process a text input (from ASR or wake word detect).

        Drives: LLM streaming → TTS streaming → audio chunks.

        V1: openclaw owns tool dispatch (web_search, etc.) and per-agent
        system prompts, so we only stream the user text in and consume
        the assistant's text back. No tool_calls flow through here.
        """
        session.transition(SessionState.THINKING)
        session.current_text = text
        session.current_turn_id += 1

        # Build messages for LLM (single user turn; openclaw keeps the
        # rest of the conversation history keyed by the `user` field).
        messages = [LLMMessage_(role="user", content=text)]

        # Stream LLM
        full_text_parts: list[str] = []
        try:
            async for event in self.llm.chat_stream(messages=messages):
                if event.kind == "text" and event.text:
                    full_text_parts.append(event.text)
                elif event.kind == "done":
                    break
                elif event.kind == "error":
                    self.log.error("llm.error", error=event.error)
                    break
        except Exception:
            self.log.exception("llm.stream_failed")
            await self._send_tts(ws, session, "抱歉，我的大脑出错了。")
            session.transition(SessionState.IDLE)
            return

        full_text = "".join(full_text_parts).strip()

        if not full_text:
            full_text = "嗯，我还没想好怎么回答。"

        # Send LLM emotion/text cue
        await ws.send(serialize_server_message(
            LLMMessage(
                session_id=session.session_id,
                emotion="happy",
                text="",
            )
        ))

        # 3) TTS — stream the text
        await self._send_tts(ws, session, full_text)

        # Clear audio buffer after the turn is complete
        session.clear_audio()
        session.transition(SessionState.IDLE)

    async def _send_tts(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        text: str,
    ) -> None:
        """Send TTS for the given text.

        Streams:
          tts.start → tts.sentence_start,text → Opus frames → tts.stop
        """
        session.transition(SessionState.SPEAKING)

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
            from .protocol.audio import OpusCodec
            do_encode = isinstance(tts_codec, OpusCodec)

            pcm_buf = bytearray()
            async for chunk in self.tts.synthesize_stream(text, sample_rate=tts_sr):
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
        except Exception:
            self.log.exception("tts.failed")

        # TTS stop
        await ws.send(serialize_server_message(
            TTSMessage(session_id=session.session_id, state="stop")
        ))
