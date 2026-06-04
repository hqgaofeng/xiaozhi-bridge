"""Cloud TTS provider skeleton.

RESERVED FOR FUTURE V2 WORK. Do not instantiate in production.

This module mirrors the ASR side (:mod:`xiaozhi_bridge.asr.cloud`):
it locks in the provider-name space and config schema so a future
cloud TTS (edge-tts / Aliyun SAMI / Volcengine / GPT-SoVITS-hosted)
can be added without changing the bridge protocol or config layout.

Decision log:
- V2 #1 (2026-06-04) deferred concrete TTS choice to V2 #2.
  V2 #1 only re-asserts the abstraction (this skeleton).
- The provider name "cloud" is intentionally generic. Concrete
  providers (edge, aliyun_tts, volcengine_tts, gpt_sovits) should
  subclass this skeleton and register under their own name.

Adding a real cloud provider later (sketch, not implementation):
    @register_tts("edge")
    class EdgeTTS(CloudTTSBase):
        async def synthesize_stream(self, text, sample_rate=24000):
            # 1. Read voice/rate/volume from self.options
            # 2. Use edge-tts Python lib (communicate stream)
            # 3. Re-sample to target sample_rate, yield TTSChunks
            ...

Config schema already reserved in config.example.yaml under `tts:`:
    tts:
      provider: cloud         # ← this skeleton (NOT YET IMPLEMENTED)
      voice: zh-CN-XiaoxiaoNeural
      rate: "+0%"
      volume: "+0%"
      options:
        vendor: edge          # concrete vendor
        # edge-tts: no credentials needed (free Microsoft service)
        # aliyun_tts: app_key, access_token
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .base import TTSBase, TTSChunk, TTSError, register_tts


@register_tts("cloud")
class CloudTTSBase(TTSBase):
    """Skeleton for cloud-based TTS providers (NOT YET IMPLEMENTED).

    All concrete cloud TTS providers (edge-tts / Aliyun / Volcengine /
    hosted GPT-SoVITS) should subclass this and implement
    :meth:`synthesize_stream`.

    Subclasses MUST:
        - Read credentials from ``self.options`` (NEVER hardcode).
        - Yield :class:`TTSChunk` in a streaming fashion (first chunk
          has ``is_first=True``, last has ``is_last=True``).
        - Yield PCM int16 mono at the requested ``sample_rate``.
        - Raise :class:`TTSError` on any failure.
    """

    name = "cloud"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        # Voice/rate/volume live at the top-level TTSConfig (not in
        # options), so subclasses should read them via constructor args
        # — see EdgeTTS (future) for the pattern. We don't read them
        # here because TTSConfig isn't passed to the provider.
        self.vendor = self.options.get("vendor", "")

    async def synthesize_stream(
        self, text: str, sample_rate: int = 24000
    ) -> AsyncIterator[TTSChunk]:
        """NOT IMPLEMENTED — reserved for future V2 work."""
        raise TTSError(
            "Cloud TTS provider is not implemented yet. "
            "Use provider=mock (silent) for now. "
            "Concrete vendors (edge/aliyun_tts/volcengine_tts/gpt_sovits) "
            "are tracked in the V2 roadmap (post-launch)."
        )
        yield  # unreachable; makes this a generator for type checkers
