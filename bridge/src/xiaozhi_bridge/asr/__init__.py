"""ASR (Automatic Speech Recognition) abstraction.

Define a common interface and a registry, so users can swap providers
(Aliyun, Tencent, Xunfei, local Whisper, sherpa-onnx, etc.) via config.

Registered providers (V2 #1, 2026-06-04):
  - mock       — returns a fixed/random phrase regardless of audio
  - sherpa_onnx — local ONNX streaming model (CPU). NOT YET IMPLEMENTED.
  - cloud      — skeleton for Aliyun/Tencent/iFlytek/Volcengine. NOT YET IMPLEMENTED.
"""

from . import cloud, mock, sherpa_onnx  # noqa: F401  (registers via @register_asr)
from .base import (
    ASRBase,
    ASRError,
    ASRResult,
    get_asr,
    list_asr_providers,
    register_asr,
)

__all__ = [
    "ASRBase",
    "ASRError",
    "ASRResult",
    "get_asr",
    "list_asr_providers",
    "register_asr",
]
