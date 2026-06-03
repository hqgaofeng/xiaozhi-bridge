"""Mock TTS implementation for testing.

Generates a short silence PCM chunk. Useful when TTS is not configured
but the protocol path needs to complete end-to-end.
"""

from __future__ import annotations

import asyncio
import math
import struct
from collections.abc import AsyncIterator

from .base import TTSBase, TTSChunk, register_tts


@register_tts("mock")
class MockTTS(TTSBase):
    """Synthesizes silence (or a tone) for the given text length.

    Configurable via options:
        - mode: "silence" (default) | "tone"
        - chunk_ms: chunk size in ms (default 60)
    """

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(options)
        self.mode = self.options.get("mode", "silence")
        self.chunk_ms = int(self.options.get("chunk_ms", 60))

    async def synthesize_stream(
        self, text: str, sample_rate: int = 24000
    ) -> AsyncIterator[TTSChunk]:
        # Approximate duration from text length (1 char ≈ 150ms)
        duration_ms = max(300, min(8000, len(text) * 150))
        chunk_samples = sample_rate * self.chunk_ms // 1000
        n_chunks = duration_ms // self.chunk_ms

        first = True
        for i in range(n_chunks):
            await asyncio.sleep(self.chunk_ms / 1000 / 4)  # fast mock

            pcm = self._make_chunk(sample_rate, chunk_samples, freq=440 if self.mode == "tone" else 0)
            yield TTSChunk(
                pcm=pcm,
                text=text,
                sample_rate=sample_rate,
                is_first=first,
                is_last=(i == n_chunks - 1),
            )
            first = False

    def _make_chunk(self, sample_rate: int, n_samples: int, freq: float = 0) -> bytes:
        """Make a PCM int16 chunk. freq=0 → silence."""
        if freq == 0:
            return b"\x00\x00" * n_samples

        # Generate a sine wave at given frequency, low amplitude
        amp = 0x0FFF  # ~10% of max
        samples = []
        for n in range(n_samples):
            t = n / sample_rate
            sample = int(amp * math.sin(2 * math.pi * freq * t))
            samples.append(struct.pack("<h", sample))
        return b"".join(samples)
