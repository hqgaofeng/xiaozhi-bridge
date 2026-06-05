"""Turn pipeline: ASR → LLM tool-use loop → TTS (V2 #11c).

V2 #11c refactor: extracted from server.py `_process_turn`
(43 lines) + `_process_text` (158 lines). Behavior preserved
1:1.

Pipeline:
  1. ASR: PCM → text
  2. LLM: text → assistant response (with optional tool calls)
     - tool calls go through the ToolManager
     - loop until the LLM stops calling tools (max 5 iterations)
  3. TTS: assistant text → device audio
  4. DB: persist user + assistant text
"""

from __future__ import annotations

import json
from typing import Any

import websockets

from ..llm.base import Message as LLMMessage_
from ..protocol import LLMMessage, SessionState, STTMessage, serialize_server_message


async def process_turn(
    server: Any,
    ws: Any,
    session: Any,
) -> None:
    """Process one turn: ASR → LLM → TTS.

    Called when the device sends listen=stop (end of recording).
    """
    pcm = session.clear_audio()
    if not pcm:
        server.log.info("turn.empty_audio", session_id=session.session_id)
        await server._transition(session, SessionState.IDLE)
        return

    await server._transition(session, SessionState.THINKING)

    # 1) ASR: PCM → text
    try:
        asr_result = await server.asr.transcribe(
            pcm,
            sample_rate=session.audio_params.sample_rate,
            channels=session.audio_params.channels,
        )
    except Exception:
        server.log.exception("asr.failed")
        await server._send_tts(ws, session, "抱歉，我没听清楚。")
        await server._transition(session, SessionState.IDLE)
        return

    text = asr_result.text.strip()
    if not text:
        await server._transition(session, SessionState.IDLE)
        return

    # Send STT result to device (so it can show on screen)
    await ws.send(serialize_server_message(
        STTMessage(session_id=session.session_id, text=text)
    ))

    # 2) LLM + 3) TTS
    await process_text(server, ws, session, text)


async def process_text(
    server: Any,
    ws: Any,
    session: Any,
    text: str,
) -> None:
    """Process a text input (from ASR or wake word detect).

    Drives: LLM streaming → (optional tool dispatch) → TTS streaming.

    V2 #7: bridge owns tool dispatch for esp32-side tools. When the LLM
    emits a TOOL_CALL event, we:
      1. Resolve the tool name against the ToolManager
      2. Invoke the tool (FunctionTool runs locally; DeviceMCPExecutor
         forwards a JSON-RPC `tools/call` to esp32 and awaits the
         matching response)
      3. Append the result to the message list as a role=tool entry
      4. Resume chat_stream with the augmented messages
      5. Loop until the LLM stops calling tools (max iterations to
         prevent infinite loops)
    """
    await server._transition(session, SessionState.THINKING)
    session.current_text = text
    session.current_turn_id += 1

    # Build messages for LLM (single user turn; openclaw keeps the
    # rest of the conversation history keyed by the `user` field).
    messages: list[LLMMessage_] = [LLMMessage_(role="user", content=text)]

    # V2 #7: build the tools list (OpenAI shape) from the MCP
    # registry. The LLM will see these in tools=... and may
    # emit tool_calls for any of them.
    tools_payload = server._build_llm_tools_payload()

    # Stream LLM with tool-use loop (V2 #7)
    full_text_parts: list[str] = []
    try:
        for _ in range(5):  # max tool-use iterations
            tool_dispatched = False
            # Track the text the LLM produced in THIS iteration,
            # so we can attach it to the assistant tool_calls turn
            # (OpenAI API contract: if a turn has both text and
            # tool_calls, both must be present in the next request
            # — sending tool_calls alone causes 400 errors on
            # some backends).
            iter_text_parts: list[str] = []
            async for event in server.llm.chat_stream(
                messages=messages, tools=tools_payload,
            ):
                if event.kind == "text" and event.text:
                    full_text_parts.append(event.text)
                    iter_text_parts.append(event.text)
                elif event.kind == "tool_call" and event.tool_call:
                    # LLM wants to invoke a tool. Forward it.
                    tc = event.tool_call
                    server.log.info(
                        "llm.tool_call",
                        session_id=session.session_id,
                        name=tc.get("name"),
                        args=tc.get("arguments"),
                    )
                    # Append the assistant's tool_call turn to
                    # messages (required for OpenAI tool-use API
                    # contract: every tool result must be preceded
                    # by the matching assistant tool_calls turn).
                    # If the LLM produced text BEFORE the tool call
                    # (common when the LLM says "let me check..."),
                    # we must include it in `content`; some
                    # backends reject tool_calls-only turns.
                    iter_text = "".join(iter_text_parts)
                    messages.append(LLMMessage_(
                        role="assistant",
                        content=iter_text,
                        tool_calls=[{
                            "id": tc.get("id") or f"call_{session.current_turn_id}",
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(tc.get("arguments", {})),
                            },
                        }],
                    ))
                    # Invoke the tool via the MCP registry.
                    tool_result_text = await server._dispatch_tool(
                        session, tc.get("name", ""), tc.get("arguments", {}),
                    )
                    # Append the tool result as a role=tool message
                    # (must reference the assistant's tool_call id).
                    messages.append(LLMMessage_(
                        role="tool",
                        content=tool_result_text,
                        tool_call_id=tc.get("id") or f"call_{session.current_turn_id}",
                    ))
                    # Set flag to indicate we dispatched a tool
                    # and need another chat_stream iteration.
                    tool_dispatched = True
                    break
                elif event.kind == "done":
                    break
                elif event.kind == "error":
                    server.log.error("llm.error", error=event.error)
                    break
            # If the inner stream finished without dispatching a
            # tool, we're done with the outer loop.
            if not tool_dispatched:
                break
            # Otherwise loop again with the augmented messages.
    except Exception:
        server.log.exception("llm.stream_failed")
        await server._send_tts(ws, session, "抱歉，我的大脑出错了。")
        await server._transition(session, SessionState.IDLE)
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

    # 3) TTS — stream the text. If the device disconnects mid-TTS
    # (V2 #8.4), tts_pipeline.send_tts surfaces ConnectionClosed;
    # we still want to persist the assistant turn to DB before
    # the connection's finally block tears down the session.
    try:
        await server._send_tts(ws, session, full_text)
    except websockets.exceptions.ConnectionClosed:
        server.log.info(
            "tts.connection_closed",
            session_id=session.session_id,
        )
        # Fall through to DB persistence and IDLE.

    # V2 #3: persist the turn (user text + assistant text) to sqlite
    if server._db is not None:
        try:
            await server._db.record_conversation(
                device_id=session.device_id,
                session_id=session.session_id,
                stt_text=text,
                assistant_text=full_text,
                llm_status="ok",
            )
        except Exception as e:
            server.log.warning("db.record_conversation_failed", error=str(e))

    # Clear audio buffer after the turn is complete
    session.clear_audio()
    await server._transition(session, SessionState.IDLE)
