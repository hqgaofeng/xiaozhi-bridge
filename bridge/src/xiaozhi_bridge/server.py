"""WebSocket server for xiaozhi-esp32 devices.

This is the heart of the bridge:
- Accepts WebSocket connections from devices
- Parses xiaozhi protocol messages
- Orchestrates ASR → LLM → TTS pipeline
- Forwards MCP JSON-RPC messages

Each connection runs an independent asyncio task with its own SessionContext.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any

import websockets
from websockets.legacy.server import WebSocketServerProtocol

from .asr import get_asr
from .config import AppConfig
from .llm import get_llm
from .mcp import MCPServer
from .mcp.handlers import (
    build_llm_tools_payload,
    cleanup_session_tools,
    register_device_tools,
)
from .mcp.manager import (
    DeviceMCPExecutor,
    FunctionToolExecutor,
    ToolManager,
    ToolType,
)
from .protocol import (
    AbortMessage,
    HelloMessage,
    ListenMessage,
    MCPMessage,
    ServerHello,
    SessionContext,
    parse_client_message,
    serialize_server_message,
)
from .tts import get_tts
from .vad import SileroVADProvider

log = logging.getLogger(__name__)


# --- Main server class ---


def _check_auth(
    auth_header: str | None,
    device_id: str | None,
    per_device_tokens: dict[str, str],
    global_token: str,
) -> tuple[bool, str]:
    """V2 #6.1: validate the Authorization header against the
    per-device map (if the device_id is listed) or the global
    token (fallback).

    V2 #6.2: return (ok, reason) instead of just bool so the
    WS handshake can close with a specific WebSocket reason
    (the client side + bridge logs both surface the reason).
    Reasons:
      - ""  : allowed (no reason needed)
      - "no_authorization_header" : client didn't send one
      - "wrong_token"             : client sent a non-matching
        bearer. Doesn't disclose whether the device_id is in the
        map or whether the global token differs (constant-time
        failure messages, prevents side-channel enumeration).
      - "malformed_authorization" : wrong scheme (Basic, Digest,
        lowercase 'bearer', etc.) or trailing/leading whitespace.
    The V2 #6.1 docstring rules still apply:
      1. per_device[device_id] (if listed) — must match
      2. global_token                  — must match
      3. neither set → no auth (allow)

    Why a pure function (not a method)? It has no I/O and no
    side effects — easy to unit-test the policy in isolation
    from the WebSocket handshake flow.
    """
    # 1. Per-device lookup.
    expected = None
    if device_id and device_id in per_device_tokens:
        expected = per_device_tokens[device_id]
    # 2. Global fallback when per-device doesn't apply.
    elif global_token:
        expected = global_token
    # 3. No policy = allow.
    if not expected:
        return True, ""
    # Policy in effect — bearer must match exactly.
    if not auth_header:
        return False, "no_authorization_header"
    # Basic scheme sanity — distinguish "scheme wrong" from
    # "scheme right but value wrong" so the firmware can fix
    # the right thing.
    if not auth_header.startswith("Bearer "):
        return False, "malformed_authorization"
    # Compare exact match; trailing/leading whitespace makes
    # the bearer not match. We surface this as 'wrong_token'
    # (not 'malformed') because the scheme IS Bearer, the
    # value is just wrong.
    if auth_header != f"Bearer {expected}":
        return False, "wrong_token"
    return True, ""


def _get_header(ws: WebSocketServerProtocol, name: str, default: str | None = None) -> str | None:
    """Read a header from a WebSocket connection, supporting the three
    websockets API surfaces that have shipped:

    - websockets < 14 / legacy:    ``ws.request_headers``
    - websockets 14-15:           ``ws.handshake.headers`` (property
                                  that returned the parsed Request)
    - websockets 16+:             ``ws.request.headers`` (Request is
                                  a regular attribute, ``handshake`` is
                                  a method that performs the upgrade).

    We need all three because pyproject only pins ``websockets>=13.0``,
    and the API broke twice in the 14/16 majors. Tested live on 16.0
    in V2 #4 after the V2 #3 e2e missed the bug (it had ``device_id``
    silently fall to None because no path matched the new API).
    """
    # Legacy: < 14
    rh = getattr(ws, "request_headers", None)
    if rh is not None:
        return rh.get(name, default)
    # websockets 16+: request is a plain attribute
    req = getattr(ws, "request", None)
    if req is not None and getattr(req, "headers", None) is not None:
        return req.headers.get(name, default)
    # websockets 14-15: handshake is a property returning the Request
    hs = getattr(ws, "handshake", None)
    if (
        hs is not None
        and not callable(hs)
        and getattr(hs, "headers", None) is not None
    ):
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

        # V2 #11a: ToolManager + per-session DeviceMCPExecutor
        # (replaces the global _REGISTRY + per-call race condition
        # we found in V2 #7.7 Bug 4). The FunctionTool executor
        # keeps the global _REGISTRY for now (V1 path, no race).
        self.tool_manager = ToolManager()
        self.tool_manager.register_executor(
            ToolType.FUNCTION, FunctionToolExecutor()
        )
        self.device_mcp_executor = DeviceMCPExecutor()
        self.tool_manager.register_executor(
            ToolType.DEVICE, self.device_mcp_executor
        )

        # V2 #8.3: server-side VAD (Silero) for esp32 AFE WebRTC VAD
        # mode 0 not triggering voice_stop in real-world conditions.
        # The VAD instance is shared; per-session state is attached to
        # the session object lazily on first audio frame.
        vad_cfg = getattr(config, "vad", None)
        if vad_cfg is not None and vad_cfg.provider == "silero":
            model_path = vad_cfg.model_path
            if not model_path:
                # Default path: bridge/models/silero_vad/data/silero_vad.onnx
                model_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "models", "silero_vad", "data", "silero_vad.onnx",
                )
            self.vad: SileroVADProvider | None = None
            if os.path.isfile(model_path):
                self.vad = SileroVADProvider(
                    model_path=model_path,
                    threshold=vad_cfg.threshold,
                    threshold_low=vad_cfg.threshold_low,
                    min_silence_duration_ms=vad_cfg.min_silence_duration_ms,
                    frame_window_threshold=vad_cfg.frame_window_threshold,
                )
                self.log.info("vad.loaded", model_path=model_path)
            else:
                self.log.warning("vad.model_missing", model_path=model_path)
        else:
            self.vad = None
            self.log.info("vad.disabled", reason="provider!=silero")

        # Track active sessions
        self.sessions: dict[str, SessionContext] = {}

        # Cache audio codecs per session (Opus decoder is stateful)
        self._codecs: dict[str, Any] = {}

        # WebSocket server
        self._server: Any = None

        # V2 #3: optional sqlite db for cross-process state with the
        # HTTP API. Set via XIAOZHI_API__DB_PATH; if the API module
        # is importable AND the db is reachable, we write through.
        # Failures here MUST NOT break the websocket hot path.
        self._db = None
        if os.environ.get("XIAOZHI_API__DB_PATH"):
            try:
                from .api.db import BridgeDB
                # Don't reuse the API process's singleton — bridge
                # gets its own connection to the same file.
                self._db = BridgeDB(path=os.environ["XIAOZHI_API__DB_PATH"])
            except Exception as e:
                self.log.warning("db.init_failed", error=str(e))

    async def start(self) -> None:
        """Start the WebSocket server."""
        if self._db is not None:
            try:
                await self._db.connect()
                self.log.info("db.connected", path=str(self._db.path))
            except Exception as e:
                self.log.warning("db.connect_failed", error=str(e))
                self._db = None

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
        if self._db is not None:
            with contextlib.suppress(Exception):
                await self._db.close()
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
            # V2 #6.1: per-device token takes precedence over the
            # legacy single-token config. Empty map + empty
            # auth_token = no auth enforced (preserves V2 #5 default
            # so the prod firmware that doesn't send an
            # Authorization header keeps working).
            device_id = _get_header(ws, "Device-Id")
            auth_header = _get_header(ws, "Authorization", "")
            ok, reason = _check_auth(
                auth_header,
                device_id,
                self.config.device.auth_tokens,
                self.config.device.auth_token,
            )
            if not ok:
                # V2 #6.2: surface the specific auth failure to
                # the firmware (via ws close reason) AND the bridge
                # log (via structlog event). The close reason is
                # one of 'no_authorization_header' /
                # 'wrong_token' / 'malformed_authorization' so
                # the operator can grep the log and see exactly
                # which case fired.
                self.log.warning(
                    "handshake.unauthorized",
                    peer=peer,
                    device_id=device_id,
                    reason=reason,
                )
                # WebSocket close reason is limited to 123 bytes
                # (RFC 6455 §7.4.1); our 3 reasons are well under.
                await ws.close(code=1001, reason=reason)
                return

            # Create session
            session = SessionContext.from_hello(msg, device_id=device_id)
            self.sessions[session.session_id] = session
            self.log.info(
                "session.created",
                session_id=session.session_id,
                device_id=device_id,
            )

            # V2 #7: register device-side tools (set_volume, etc.) as
            # LLM-callable MCP tools. These forward through the xiaozhi
            # `mcp` channel to esp32, which is itself an MCP server
            # (see esp32's mcp_server.cc). The future dance: tool __call__
            # awaits the future; the future is resolved in _handle_mcp
            # when the device sends the JSON-RPC response.
            #
            # V2 #11a: extracted to mcp/handlers.py so the server
            # file focuses on connection lifecycle.
            register_device_tools(self, session, ws, self.device_mcp_executor)

            # V2 #3: persist to sqlite for the HTTP API
            if self._db is not None:
                try:
                    await self._db.open_session(session.session_id, device_id)
                except Exception as e:
                    self.log.warning("db.open_session_failed", error=str(e))

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
                # V2 #3: close session in db before evicting
                if self._db is not None:
                    try:
                        await self._db.close_session(session.session_id)
                    except Exception as e:
                        self.log.warning("db.close_session_failed", error=str(e))
                self.sessions.pop(session.session_id, None)
                # Clean up cached codec
                self._codecs.pop(session.session_id, None)
                # V2 #8.4: clean up per-session VAD state to avoid leaks
                if self.vad is not None:
                    self.vad.reset_session_state(session)
                # V2 #8.4: cancel any pending wake-grace task
                if hasattr(self, "_wake_grace_tasks"):
                    self._cancel_wake_grace(session)
                # V2 #7 cleanup: unregister device-tool handlers owned
                # by this session so the global registry doesn't leak
                # stale ws/session closures across reconnects. Until we
                # move to a per-session MCP server (V2 #7.7), this is
                # the safest mitigation against cross-session races.
                #
                # V2 #11a: extracted to mcp/handlers.py; the old
                # _cleanup_session_tools is kept as a thin shim for
                # backward compat with V2 #7 tests.
                if hasattr(self, "_session_tool_owners"):
                    cleanup_session_tools(self, session.session_id)
                # V2 #7: cancel any pending MCP futures that never got
                # a response (esp32 disconnected mid-tool-call). This
                # prevents "Task was destroyed but it is pending" warnings
                # at process exit and frees the dict promptly.
                for req_id, future in list(session.pending_mcp_calls.items()):
                    if not future.done():
                        future.set_exception(
                            RuntimeError(f"session closed before mcp response (id={req_id})")
                        )
                session.pending_mcp_calls.clear()
                self.log.info("session.closed", session_id=session.session_id)

    async def _main_loop(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
    ) -> None:
        """Main message loop for a connected device.

        V2 #11b: replaces the V2 #7 match-case dispatch with
        a registry-based TextMessageProcessor. Adding a new
        message type = create XxxTextMessageHandler + register.
        """
        from .handle import TextMessageProcessor, default_registry
        processor = TextMessageProcessor(default_registry)
        async for raw in ws:
            if isinstance(raw, bytes):
                # Audio frame (Opus) — not a text message, handled inline
                await self._handle_audio(ws, session, raw)
            else:
                # JSON text frame → dispatch via registry
                await processor.process_message(self, ws, session, raw)

    async def _transition(self, session: SessionContext, new_state) -> None:
        """V2 #3 helper: transition + persist to db (best-effort)."""
        session.transition(new_state)
        if self._db is not None:
            await session.persist_state(self._db)

    # --- Message handlers ---

    async def _handle_audio(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        opus_frame: bytes,
    ) -> None:
        """V2 #11c: thin shim → audio/handler.handle_audio."""
        from .audio.handler import handle_audio as _handle_audio
        await _handle_audio(self, ws, session, opus_frame)

    async def _handle_listen(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        msg: ListenMessage,
    ) -> None:
        """V2 #11b: thin shim → handle/textHandler/listenMessageHandler.

        Kept as a method shim so any legacy code that calls
        `server._handle_listen(ws, session, msg)` (e.g. the
        V2 #7 MagicMock tests) continues to work. The actual
        dispatch goes through the new registry in _main_loop.
        """
        from .handle.textHandler.listenMessageHandler import ListenTextMessageHandler
        handler = ListenTextMessageHandler()
        await handler.handle(self, ws, session, msg)

    async def _end_wake_grace(self, session: SessionContext) -> None:
        """V2 #11c: thin shim → audio/handler.end_wake_grace."""
        from .audio.handler import end_wake_grace as _end_wake_grace
        await _end_wake_grace(self, session)

    def _cancel_wake_grace(self, session: SessionContext) -> None:
        """V2 #11c: thin shim → audio/handler.cancel_wake_grace."""
        from .audio.handler import cancel_wake_grace as _cancel_wake_grace
        _cancel_wake_grace(self, session)

    async def _handle_abort(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        msg: AbortMessage,
    ) -> None:
        """V2 #11b: thin shim → handle/textHandler/abortMessageHandler."""
        from .handle.textHandler.abortMessageHandler import AbortTextMessageHandler
        handler = AbortTextMessageHandler()
        await handler.handle(self, ws, session, msg)

    async def _handle_mcp(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        msg: MCPMessage,
    ) -> None:
        """V2 #11b: thin shim → handle/textHandler/mcpMessageHandler."""
        from .handle.textHandler.mcpMessageHandler import McpTextMessageHandler
        handler = McpTextMessageHandler()
        await handler.handle(self, ws, session, msg)

    # V2 #7: send an MCP tools/call request to the device and stash
    # the response future so _handle_mcp can resolve it when the
    # device replies. Used by DeviceToolHandler instances registered
    # as LLM-callable tools.
    #
    # V2 #11a: extracted to mcp/handlers.send_mcp_call (thin shim
    # kept here for V2 #7 test compatibility; the new code path
    # in register_device_tools imports handlers.send_mcp_call
    # directly).
    async def _send_mcp_call(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        tool_name: str,
        arguments: dict,
        future: asyncio.Future,
    ) -> None:
        from .mcp.handlers import send_mcp_call as _send_mcp_call
        await _send_mcp_call(self, ws, session, tool_name, arguments, future)

    def _register_device_tools(
        self,
        session: SessionContext,
        ws: WebSocketServerProtocol,
    ) -> None:
        """V2 #7 + V2 #11a: thin shim → mcp/handlers.register_device_tools.

        Kept as a method so the V2 #7 test (`test_mcp_v27_e2e`)
        and the existing call sites in `_handle_connection`
        don't need to change.
        """
        register_device_tools(self, session, ws, self.device_mcp_executor)

    def _cleanup_session_tools(self, session_id: str) -> None:
        """V2 #7 + V2 #11a: thin shim → mcp/handlers.cleanup_session_tools.

        Kept as a method so the V2 #7 test
        (`test_mcp_v27_session_cleanup.py`) can still call
        `XiaozhiBridgeServer._cleanup_session_tools(server, ...)`
        with a MagicMock.
        """
        cleanup_session_tools(self, session_id)

    # --- Pipeline ---

    def _build_llm_tools_payload(self) -> list[dict]:
        """V2 #7 + V2 #11a: thin shim → mcp/handlers.build_llm_tools_payload.

        Returns an empty list if no tools are registered. The
        returned shape is the OpenAI chat completions spec:
        [{"type": "function", "function": {...}}].

        Backward compat (V2 #7 MagicMock tests): if `self` is a
        MagicMock without `tool_manager`, fall back to the
        legacy _REGISTRY path. This keeps the V2 #7 e2e tests
        working with `MagicMock` instead of a real server.
        """
        tm = getattr(self, "tool_manager", None)
        if tm is None:
            # Legacy path for tests that build a MagicMock without
            # the full server __init__.
            from .mcp import tools as tool_registry
            out: list[dict] = []
            for spec in tool_registry.list_tools(with_user_tools=False):
                out.append({
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "description": spec["description"],
                        "parameters": spec["inputSchema"],
                    },
                })
            return out
        return build_llm_tools_payload(tm)

    async def _dispatch_tool(
        self,
        session: SessionContext,
        name: str,
        arguments: dict,
    ) -> str:
        """V2 #7 + V2 #11a: thin shim → mcp/handlers.dispatch_tool.

        Dispatches via ToolManager (which knows about both
        FunctionTool and DeviceMCPExecutor paths).

        Backward compat: MagicMock tests that don't have a
        real tool_manager fall through to the legacy _REGISTRY
        path. (V2 #7 e2e test fixture.)
        """
        from .mcp.handlers import dispatch_tool as _dispatch_tool
        tm = getattr(self, "tool_manager", None)
        if tm is None:
            # Legacy fallback: use the global _REGISTRY.
            from .mcp import tools as tool_registry
            try:
                result = await tool_registry.call_tool(name, arguments)
            except KeyError:
                self.log.warning("tool.unknown", name=name)
                return f"Error: tool {name!r} not found"
            except Exception as e:
                self.log.exception("tool.failed", name=name)
                return f"Error: tool {name!r} failed: {e!r}"
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        return await _dispatch_tool(self, session, name, arguments, tm)

    async def _process_turn(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
    ) -> None:
        """V2 #11c: thin shim → pipeline/turn.process_turn."""
        from .pipeline.turn import process_turn as _process_turn
        await _process_turn(self, ws, session)

    async def _process_text(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        text: str,
    ) -> None:
        """V2 #11c: thin shim → pipeline/turn.process_text."""
        from .pipeline.turn import process_text as _process_text
        await _process_text(self, ws, session, text)

    async def _send_tts(
        self,
        ws: WebSocketServerProtocol,
        session: SessionContext,
        text: str,
    ) -> None:
        """V2 #11c: thin shim → pipeline/tts.send_tts."""
        from .pipeline.tts import send_tts as _send_tts
        await _send_tts(self, ws, session, text)
