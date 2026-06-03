"""Opus audio codec wrapper.

Wraps the opuslib library to provide:
- Decoder for incoming device audio (Opus → PCM)
- Encoder for outgoing TTS audio (PCM → Opus)

The xiaozhi-esp32 firmware uses 16 kHz mono Opus at 60 ms frame duration
for microphone upload, and 24 kHz for TTS playback. We support both.
"""

from __future__ import annotations

import asyncio

# Note: opuslib is a thin wrapper around libopus. On systems without
# libopus installed, imports will fail. We isolate this in try/except so
# the rest of the code can be type-checked / imported for tests.

try:
    import opuslib  # type: ignore
    import opuslib.api  # type: ignore

    OPUS_AVAILABLE = True
except ImportError:
    OPUS_AVAILABLE = False


class OpusCodec:
    """Opus encoder/decoder for one direction (in or out).

    Not thread-safe — use one instance per direction per session.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_duration_ms: int = 60,
        application: str = "voip",
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        # 60 ms × 16 kHz = 960 samples
        self.frame_size = sample_rate * frame_duration_ms // 1000

        if not OPUS_AVAILABLE:
            raise RuntimeError(
                "opuslib not available. Install libopus system package: "
                "apt install libopus0 libopus-dev"
            )

        # opuslib 3.0+ takes the application as a string ('voip' | 'audio'
        # | 'restricted_lowdelay'), not the old opuslib.api.decoder constants
        # which were removed in the rewrite.
        valid_apps = ("voip", "audio", "restricted_lowdelay")
        if application in ("lowdelay",):
            application = "restricted_lowdelay"
        if application not in valid_apps:
            application = "voip"
        self._app = application
        self._decoder: opuslib.Decoder | None = None
        self._encoder: opuslib.Encoder | None = None

    def _ensure_decoder(self) -> opuslib.Decoder:
        if self._decoder is None:
            self._decoder = opuslib.Decoder(self.sample_rate, self.channels)
        return self._decoder

    def _ensure_encoder(self) -> opuslib.Encoder:
        if self._encoder is None:
            self._encoder = opuslib.Encoder(self.sample_rate, self.channels, self._app)
        return self._encoder

    def decode(self, opus_frame: bytes) -> bytes:
        """Decode one Opus frame → PCM int16 bytes."""
        decoder = self._ensure_decoder()
        return decoder.decode(opus_frame, self.frame_size)

    def encode(self, pcm_frame: bytes) -> bytes:
        """Encode one PCM int16 frame → Opus bytes."""
        encoder = self._ensure_encoder()
        return encoder.encode(pcm_frame, self.frame_size)

    async def decode_stream(self, opus_iter):
        """Async helper: decode a stream of Opus frames → PCM bytes."""
        loop = asyncio.get_running_loop()
        for opus_frame in opus_iter:
            yield await loop.run_in_executor(None, self.decode, opus_frame)

    async def encode_stream(self, pcm_iter):
        """Async helper: encode a stream of PCM frames → Opus bytes."""
        loop = asyncio.get_running_loop()
        for pcm_frame in pcm_iter:
            yield await loop.run_in_executor(None, self.encode, pcm_frame)


# --- Fallback for systems without libopus ---
# During development/testing on systems without libopus, we provide
# a pass-through "codec" that doesn't actually decode. This lets
# us develop other parts of the system without audio dependencies.


class PassThroughCodec:
    """No-op codec. Passes bytes through unchanged.

    Useful for:
    - Development on systems without libopus
    - Mock testing
    - Text-only mode (audio is disabled)
    """

    sample_rate: int = 16000
    channels: int = 1
    frame_size: int = 960

    def __init__(self, *args, **kwargs) -> None:
        pass

    def decode(self, opus_frame: bytes) -> bytes:
        return opus_frame

    def encode(self, pcm_frame: bytes) -> bytes:
        return pcm_frame

    async def decode_stream(self, opus_iter):
        for frame in opus_iter:
            yield frame

    async def encode_stream(self, pcm_iter):
        for frame in pcm_iter:
            yield frame


def make_codec(sample_rate: int = 16000, channels: int = 1, frame_duration_ms: int = 60):
    """Factory: return an OpusCodec if available, else a PassThroughCodec.

    Use this in production code so the system can start even without
    libopus installed (for example, the web admin UI without audio).
    """
    if OPUS_AVAILABLE:
        try:
            return OpusCodec(sample_rate, channels, frame_duration_ms)
        except Exception:
            pass
    return PassThroughCodec()
