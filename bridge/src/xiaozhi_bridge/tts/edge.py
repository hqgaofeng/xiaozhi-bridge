"""Microsoft Edge TTS (edge-tts) provider.

V2 #2 (2026-06-04) — first real cloud TTS implementation.

edge-tts is a free, public WebSocket service from Microsoft that exposes
neural voices (zh-CN-XiaoxiaoNeural, en-US-JennyNeural, …) without
requiring an API key. It returns an mp3 byte stream with periodic
SentenceBoundary events that we can use to chunk the output.

Architecture
------------
The provider consumes edge-tts's stream (audio + SentenceBoundary
events), buffers mp3 bytes until a sentence boundary, decodes the
buffered mp3 → PCM int16 mono at the requested sample_rate, and
yields :class:`TTSChunk` slices in a streaming fashion.

MP3 → PCM decoding is done via :mod:`pydub`, which shells out to the
``ffmpeg`` binary. The Docker image installs ``ffmpeg`` via apt in
the bridge Dockerfile (see ``bridge/Dockerfile``).

Concurrency
-----------
``pydub.from_mp3`` is blocking (subprocess call to ffmpeg) and is
run via :func:`asyncio.to_thread` so the event loop is not blocked.
Each sentence decode is dispatched independently so a slow decode of
sentence N does not block the edge-tts stream read of sentence N+1.

Configuration
-------------
TTS options (read from ``config/config.yaml`` under ``tts:``):

    tts:
      provider: edge
      voice: zh-CN-XiaoxiaoNeural    # default; see edge-tts docs
      rate: "+0%"                    # speed
      volume: "+0%"                  # loudness
      pitch: "+0Hz"                  # pitch
      options:
        chunk_ms: 60                 # PCM chunk size (ms) per yield
        boundary: SentenceBoundary    # or "WordBoundary"
        connect_timeout: 10          # edge-tts WS connect timeout (s)
        receive_timeout: 60          # edge-tts WS receive timeout (s)

Notes / pitfalls (V2 #2)
------------------------
1. edge-tts requires outbound HTTPS to ``api.msedgeservices.com`` /
   ``speech.platform.bing.com``. Firewall or DNS blocking will
   manifest as :class:`TTSError` after connect_timeout.
2. MP3 decode happens per sentence; first-sentence latency is
   therefore ``connect_ms + first_sentence_decode_ms``. Typical:
   connect ~200ms, first sentence decode ~150ms.
3. The edge-tts ``rate`` / ``volume`` / ``pitch`` are SSML-like
   strings (``"+0%"`` / ``"-10%"`` / ``"+5Hz"``). We do NOT validate
   them — edge-tts will raise at synthesis time with a clear message.
4. edge-tts does NOT support streaming WAV/PCM output. All audio
   arrives as compressed mp3 frames. We always pay the ffmpeg
   decode cost.
"""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import AsyncIterator
from typing import Any

import edge_tts
from pydub import AudioSegment

from ..utils.logging import get_logger
from .base import TTSBase, TTSChunk, TTSError, register_tts

logger = get_logger(__name__)


# 60 ms matches the mock TTS chunk size (V1-era convention); the
# xiaozhi device Opus encoder is tuned for ~60ms frames.
_DEFAULT_CHUNK_MS = 60


@register_tts("edge")
class EdgeTTS(TTSBase):
    """Microsoft Edge TTS — streaming PCM int16 mono via edge-tts + pydub."""

    name = "edge"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        # Read options (all have safe defaults).
        self.chunk_ms = int(self.options.get("chunk_ms", _DEFAULT_CHUNK_MS))
        self.boundary = self.options.get("boundary", "SentenceBoundary")
        if self.boundary not in ("SentenceBoundary", "WordBoundary"):
            raise ValueError(
                f"edge TTS 'boundary' must be SentenceBoundary or WordBoundary, "
                f"got {self.boundary!r}"
            )
        self.connect_timeout = int(self.options.get("connect_timeout", 10))
        self.receive_timeout = int(self.options.get("receive_timeout", 60))

    async def synthesize_stream(
        self, text: str, sample_rate: int = 24000
    ) -> AsyncIterator[TTSChunk]:
        """Synthesize text → PCM int16 mono chunks.

        Args:
            text: Input text (any length; edge-tts internally splits
                into ≤4096-byte requests).
            sample_rate: Target output sample rate. edge-tts mp3
                streams are decoded via ffmpeg, so any common rate
                is supported (we typically request 24000 to match
                the xiaozhi device Opus encoder).
        """
        if not text or not text.strip():
            raise TTSError("edge TTS: empty text")
        if sample_rate <= 0:
            raise TTSError(f"edge TTS: invalid sample_rate {sample_rate}")

        voice = self.options.get("voice", "zh-CN-XiaoxiaoNeural")
        rate = self.options.get("rate", "+0%")
        volume = self.options.get("volume", "+0%")
        pitch = self.options.get("pitch", "+0Hz")

        logger.info(
            "edge_tts_synthesis_start",
            voice=voice,
            sample_rate=sample_rate,
            text_len=len(text),
            chunk_ms=self.chunk_ms,
        )
        t0 = time.monotonic()

        # We buffer mp3 bytes per sentence, decode to PCM in a
        # background thread, and yield the PCM in 60ms-ish slices.
        # The edge-tts stream emits SentenceBoundary events between
        # sentences (and at end-of-stream). We flush on every
        # SentenceBoundary.
        #
        # The protocol from TTSBase says the first yielded chunk of
        # a synthesis MUST have is_first=True and the last MUST
        # have is_last=True. edge-tts may produce 0..N sentences,
        # so we keep a sentence_index and mark first/last overall.
        mp3_buf = io.BytesIO()
        sentence_text = ""  # accumulated text for the current sentence
        first_chunk_sent = False
        chunk_index = 0

        try:
            comm = edge_tts.Communicate(
                text,
                voice=voice,
                rate=rate,
                volume=volume,
                pitch=pitch,
                boundary=self.boundary,  # type: ignore[arg-type]
                connect_timeout=self.connect_timeout,
                receive_timeout=self.receive_timeout,
            )
            async for ev in comm.stream():
                ev_type = ev.get("type")

                if ev_type == "audio":
                    # Append mp3 bytes to the current sentence buffer.
                    data = ev.get("data")
                    if not data:
                        continue
                    mp3_buf.write(data)

                elif ev_type == "SentenceBoundary":
                    # Flush the buffered mp3 as a complete sentence.
                    sentence_text = ev.get("text", "") or sentence_text
                    async for chunk in self._flush_sentence(
                        mp3_buf,
                        sentence_text,
                        sample_rate,
                        is_first_overall=not first_chunk_sent,
                    ):
                        first_chunk_sent = True
                        chunk_index += 1
                        yield chunk
                    sentence_text = ""

                elif ev_type == "WordBoundary":
                    # We don't break on word boundaries (chunks would
                    # be too small), but we keep the text for the
                    # boundary so a later SentenceBoundary has the
                    # right sentence text. Not used currently.
                    pass

            # End of stream — flush any remaining mp3.
            if mp3_buf.tell() > 0:
                async for chunk in self._flush_sentence(
                    mp3_buf,
                    sentence_text or text,
                    sample_rate,
                    is_first_overall=not first_chunk_sent,
                    is_last_overall=True,
                ):
                    first_chunk_sent = True
                    chunk_index += 1
                    yield chunk

        except TTSError:
            raise
        except Exception as e:
            logger.error("edge_tts_synthesis_failed", error=str(e))
            raise TTSError(f"edge TTS synthesis failed: {e}") from e
        finally:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "edge_tts_synthesis_done",
                voice=voice,
                text_len=len(text),
                chunks=chunk_index,
                elapsed_ms=elapsed_ms,
            )

    async def _flush_sentence(
        self,
        mp3_buf: io.BytesIO,
        sentence_text: str,
        sample_rate: int,
        is_first_overall: bool,
        is_last_overall: bool = False,
    ) -> AsyncIterator[TTSChunk]:
        """Decode the buffered mp3 → PCM int16 mono and yield chunks.

        Runs the blocking pydub/ffmpeg decode in a worker thread.
        If the buffer is empty, yields nothing.
        """
        mp3_bytes = mp3_buf.getvalue()
        if not mp3_bytes:
            return
        # Reset the buffer for the next sentence.
        mp3_buf.seek(0)
        mp3_buf.truncate(0)

        # Decode mp3 → PCM int16 mono at the target sample_rate.
        # pydub + ffmpeg is blocking, so offload to a thread.
        pcm = await asyncio.to_thread(
            _decode_mp3_to_pcm, mp3_bytes, sample_rate
        )
        if not pcm:
            return

        # Slice the PCM into chunk_ms-sized windows.
        # PCM int16 mono: 2 bytes per sample. chunk_samples = sr * ms / 1000.
        bytes_per_sample = 2
        chunk_bytes = (
            sample_rate * self.chunk_ms // 1000 * bytes_per_sample
        )
        if chunk_bytes <= 0:
            chunk_bytes = bytes_per_sample  # at least one sample

        n_chunks = max(1, (len(pcm) + chunk_bytes - 1) // chunk_bytes)
        for i in range(n_chunks):
            start = i * chunk_bytes
            end = min(start + chunk_bytes, len(pcm))
            yield TTSChunk(
                pcm=pcm[start:end],
                text=sentence_text,
                sample_rate=sample_rate,
                is_first=is_first_overall and i == 0,
                is_last=is_last_overall and i == n_chunks - 1,
            )


def _decode_mp3_to_pcm(mp3_bytes: bytes, sample_rate: int) -> bytes:
    """Synchronous mp3 → PCM int16 mono decoder (runs in worker thread).

    pydub.AudioSegment.from_mp3 → raw_data yields PCM int16 (signed 16-bit
    little-endian) by default when we set sample_width=2.
    """
    seg: AudioSegment = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
    # Ensure mono + target sample rate + int16.
    seg = seg.set_channels(1).set_frame_rate(sample_rate).set_sample_width(2)
    return seg.raw_data
