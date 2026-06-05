"""ASR (Automatic Speech Recognition) abstraction.

Define a common interface and a registry, so users can swap providers
(Aliyun, Tencent, Xunfei, local Whisper, sherpa-onnx, etc.) via config.

Registered providers:
  - mock       — returns a fixed/random phrase regardless of audio (V1)
  - sherpa_onnx — local ONNX streaming-zipformer (zh+en) (V2 #1, 2026-06-04)
  - cloud      — skeleton for Aliyun/Tencent/iFlytek/Volcengine (V1)
  - sensevoice — local SenseVoice (zh+en+ja+ko+yue) offline (V2 #10 C-5, 2026-06-05)
"""

from . import cloud, mock, sensevoice, sherpa_onnx  # noqa: F401  (registers via @register_asr)
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
