"""Cloud ASR provider skeleton.

RESERVED FOR FUTURE V2 WORK. Do not instantiate in production.

This module exists to lock in the provider-name space and config schema
so that a future cloud ASR (Aliyun NLS / Tencent ASR / iFlytek / Volcengine)
can be added without changing the bridge protocol or config layout.

Decision log:
- V2 #1 (2026-06-04) chose sherpa-onnx (local) as the primary ASR.
  Cloud API is deferred until "after launch" per user request.
- The provider name "cloud" is intentionally generic. Concrete
  providers (aliyun, tencent, xfyun, volcengine) should subclass
  this skeleton and register under their own name.

Adding a real cloud provider later (sketch, not implementation):
    @register_asr("aliyun")
    class AliyunASR(CloudASRBase):
        async def transcribe(self, audio, sample_rate, channels=1):
            # 1. Read app_key/access_token from self.options
            # 2. Call Aliyun NLS / RecognizeIntent API
            # 3. Map response → ASRResult (text, confidence, language)
            ...

Config schema already reserved in config.example.yaml under `asr:`:
    asr:
      provider: cloud        # ← this skeleton
      options:
        vendor: aliyun       # concrete vendor
        app_key: ${ALIYUN_APP_KEY}    # read from env
        access_token: ${ALIYUN_TOKEN} # read from env
        region: cn-shanghai
        model: paraformer-v2
"""

from __future__ import annotations

from typing import Any

from .base import ASRBase, ASRError, ASRResult, register_asr


@register_asr("cloud")
class CloudASRBase(ASRBase):
    """Skeleton for cloud-based ASR providers (NOT YET IMPLEMENTED).

    All concrete cloud ASR providers (Aliyun, Tencent, iFlytek, etc.)
    should subclass this and implement :meth:`transcribe`.

    Subclasses MUST:
        - Read credentials from ``self.options`` (NEVER hardcode).
        - Map provider response → :class:`ASRResult` (text/confidence/language).
        - Raise :class:`ASRError` on any failure (auth, network, bad audio).
        - Be safe to instantiate once and reuse across requests.
    """

    name = "cloud"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        # Validate required config keys early (subclasses extend this).
        self.vendor = self.options.get("vendor", "")
        if not self.vendor:
            # No vendor configured — we still allow construction (e.g. for
            # `list_asr_providers()` enumeration), but transcribe() will
            # raise ASRError with a clear message.
            pass

    async def transcribe(
        self, audio: bytes, sample_rate: int, channels: int = 1
    ) -> ASRResult:
        """NOT IMPLEMENTED — reserved for future V2 work.

        See module docstring for the contract a concrete provider must
        satisfy. Today, calling this raises ASRError so misconfiguration
        fails loudly rather than silently returning empty text.
        """
        raise ASRError(
            "Cloud ASR provider is not implemented yet. "
            "Use provider=sherpa_onnx (V2 #1) or provider=mock for now. "
            "Concrete vendors (aliyun/tencent/xfyun/volcengine) are tracked "
            "in the V2 roadmap (post-launch)."
        )
