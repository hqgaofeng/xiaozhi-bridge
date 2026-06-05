"""Silero VAD provider for xiaozhi-bridge.

This is a direct port of xiaozhi-esp32-server's SileroVAD implementation,
adapted for our async session lifecycle. It uses the same silero_vad.onnx
model, the same parameters (threshold=0.5, threshold_low=0.2, 1000ms
silence), and the same sliding-window + hysteresis logic.

Why server-side VAD (V2 #8.3):
    ESP32's AFE WebRTC VAD (mode 0, aggressive) often does NOT trigger
    voice_stop in real-world conditions — esp32 keeps pushing audio
    frames but never sends listen.state=stop. Bridge accumulates PCM
    forever and never triggers ASR. Official xiaozhi-esp32-server
    solves this with server-side Silero VAD; we mirror that.

V2 #8.3 design notes (kept here so future readers don't repeat mistakes):

1. Per-session state is attached to the session object (not a global dict)
   to avoid leaks when sessions close. _init_session_state() is idempotent.

2. We decode opus → int16 PCM using opuslib (same decoder used by
   _handle_audio). Sample rate is 16000 (per Silero VAD spec).

3. Silero VAD expects exactly 512 samples (32ms @ 16kHz) per inference
   call. We accumulate PCM in client_audio_buffer until we have enough
   samples, then run inference, then slide the window by 512.

4. The onnx model takes 3 inputs: input (1, 512 or 576), state (2,1,128),
   sr (int64). State must be persisted across calls (h_t + c_t for LSTM).

5. Threshold: speech_prob >= 0.5 → voice; <= 0.2 → silence; else use
   last frame's decision (hysteresis to avoid flapping).

6. Sliding window: 3 frames. client_have_voice = window.count(True) >= 3.

7. voice_stop: after we HAD voice (client_have_voice) and now no voice
   (current frame is silence) AND >= 1000ms since last voice → set
   client_voice_stop = True. This is the trigger for ASR.

8. Manual mode: when client_listen_mode == "manual", return True
   unconditionally (cache all audio, let esp32 control stop).

Reference:
    xiaozhi-esp32-server/core/providers/vad/silero.py
    xiaozhi-esp32-server/core/handle/receiveAudioHandle.py
    xiaozhi-esp32-server/core/providers/asr/base.py::receive_audio
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np
import onnxruntime

from xiaozhi_bridge.vad.base import VADProviderBase

if TYPE_CHECKING:
    pass  # session type is duck-typed


# Silero VAD model constants (do not change — these are the model's spec)
SAMPLE_RATE = 16000
SAMPLES_PER_FRAME = 512  # 32ms @ 16kHz
FRAME_BYTES = SAMPLES_PER_FRAME * 2  # int16 = 2 bytes/sample

# Decoder sample count: 60ms opus frame @ 16kHz = 960 samples
OPUS_FRAME_SAMPLES = 960


class SileroVADProvider(VADProviderBase):
    """Silero VAD provider (server-side voice activity detection).

    Loads silero_vad.onnx on first instantiation, then runs per-session
    state attached to the session object passed in is_vad().

    Configurable via constructor:
        model_path: path to silero_vad.onnx
        threshold: high threshold (default 0.5)
        threshold_low: low threshold for hysteresis (default 0.2)
        min_silence_duration_ms: silence duration to trigger voice_stop
            (default 1000ms)
        frame_window_threshold: sliding window size (default 3)
    """

    def __init__(
        self,
        model_path: str,
        threshold: float = 0.5,
        threshold_low: float = 0.2,
        min_silence_duration_ms: int = 1000,
        frame_window_threshold: int = 3,
    ) -> None:
        self.threshold = threshold
        self.threshold_low = threshold_low
        self.silence_threshold_ms = min_silence_duration_ms
        self.frame_window_threshold = frame_window_threshold

        # Load ONNX model
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )

    def _init_session_state(self, session: Any) -> None:
        """Attach per-session VAD state if not already present.

        Idempotent — safe to call on every is_vad() invocation.
        """
        if not hasattr(session, "_vad_audio_buffer"):
            session._vad_audio_buffer = bytearray()
        if not hasattr(session, "_vad_state"):
            # Silero VAD expects state shape (2, 1, 128) for LSTM (h+c)
            session._vad_state = np.zeros((2, 1, 128), dtype=np.float32)
        if not hasattr(session, "_vad_context"):
            # Last 64 samples are concatenated to the next frame
            session._vad_context = np.zeros((1, 64), dtype=np.float32)
        if not hasattr(session, "_vad_voice_window"):
            session._vad_voice_window: list[bool] = []
        if not hasattr(session, "client_have_voice"):
            session.client_have_voice = False
        if not hasattr(session, "client_voice_stop"):
            session.client_voice_stop = False
        if not hasattr(session, "vad_last_voice_time"):
            session.vad_last_voice_time = 0.0
        if not hasattr(session, "last_is_voice"):
            session.last_is_voice = False
        if not hasattr(session, "just_woken_up"):
            # Mirror official: 2-second grace period after wake word
            session.just_woken_up = False
        if not hasattr(session, "client_voice_stop_pending"):
            session.client_voice_stop_pending = False

    def reset_session_state(self, session: Any) -> None:
        """Reset VAD state for a new turn (after ASR is triggered).

        Mirrors conn.reset_audio_states() in official server.
        """
        if hasattr(session, "_vad_audio_buffer"):
            session._vad_audio_buffer = bytearray()
        if hasattr(session, "_vad_voice_window"):
            session._vad_voice_window = []
        session.client_have_voice = False
        session.client_voice_stop = False
        session.vad_last_voice_time = 0.0
        session.last_is_voice = False

    def is_vad(self, session: Any, opus_packet: bytes) -> bool:
        """Run VAD on a single Opus packet.

        Returns:
            True if the sliding window says voice is present.
        Side effects:
            - Sets session.client_voice_stop = True when 1000ms silence
              is detected after voice.
            - Updates session.client_have_voice, session._vad_state, etc.
        """
        # Manual mode: cache everything, esp32 controls stop
        if getattr(session, "client_listen_mode", "auto") == "manual":
            return True

        # Just-woken-up grace: ignore VAD for 2s after wake word
        # (avoids false positive from wake word audio tail)
        if getattr(session, "just_woken_up", False):
            return False

        try:
            self._init_session_state(session)

            # Decode opus → int16 PCM (16kHz mono)
            opus_decoder = self._get_opus_decoder(session)
            pcm_frame = opus_decoder.decode(opus_packet, OPUS_FRAME_SAMPLES)
            session._vad_audio_buffer.extend(pcm_frame)

            client_have_voice = False

            # Process all complete 512-sample frames in the buffer
            while len(session._vad_audio_buffer) >= FRAME_BYTES:
                chunk = bytes(session._vad_audio_buffer[:FRAME_BYTES])
                del session._vad_audio_buffer[:FRAME_BYTES]

                # int16 → float32 normalized to [-1, 1]
                audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                audio_float32 = audio_int16.astype(np.float32) / 32768.0

                # Concatenate context (last 64 samples) with current frame
                audio_input = np.concatenate(
                    [session._vad_context, audio_float32.reshape(1, -1)],
                    axis=1,
                ).astype(np.float32)

                ort_inputs = {
                    "input": audio_input,
                    "state": session._vad_state,
                    "sr": np.array(SAMPLE_RATE, dtype=np.int64),
                }
                out, state = self.session.run(None, ort_inputs)
                session._vad_state = state
                session._vad_context = audio_input[:, -64:]
                speech_prob = out.item()

                # Dual-threshold hysteresis
                if speech_prob >= self.threshold:
                    is_voice = True
                elif speech_prob <= self.threshold_low:
                    is_voice = False
                else:
                    is_voice = session.last_is_voice
                session.last_is_voice = is_voice

                # Sliding window: count True in window
                session._vad_voice_window.append(is_voice)
                # Keep window bounded
                if len(session._vad_voice_window) > self.frame_window_threshold:
                    session._vad_voice_window.pop(0)
                client_have_voice = (
                    sum(session._vad_voice_window) >= self.frame_window_threshold
                )

                # voice_stop detection: had voice, now no voice, >= 1000ms
                if session.client_have_voice and not client_have_voice:
                    stop_duration = time.time() * 1000 - session.vad_last_voice_time
                    if stop_duration >= self.silence_threshold_ms:
                        session.client_voice_stop = True

                # Track voice time
                if client_have_voice:
                    session.client_have_voice = True
                    session.vad_last_voice_time = time.time() * 1000

            return client_have_voice

        except Exception as e:
            # Never let VAD errors crash the audio pipeline
            import structlog
            structlog.get_logger().warning("vad.error", error=str(e))
            return False

    def _get_opus_decoder(self, session: Any) -> Any:
        """Get or create the per-session Opus decoder for VAD.

        We use a separate decoder from _handle_audio's decoder to avoid
        state corruption (opuslib decoders are stateful). The decoder
        is 16kHz mono, matching Silero VAD spec.
        """
        if not hasattr(session, "_vad_opus_decoder"):
            import opuslib
            session._vad_opus_decoder = opuslib.Decoder(SAMPLE_RATE, 1)
        return session._vad_opus_decoder
