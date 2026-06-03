"""ASR (Automatic Speech Recognition) abstraction.

Define a common interface and a registry, so users can swap providers
(Aliyun, Tencent, Xunfei, local Whisper, etc.) via config.
"""

from . import mock  # noqa: F401  (registers MockASR)
from .base import ASRBase, ASRResult, get_asr, list_asr_providers, register_asr

__all__ = ["ASRBase", "ASRResult", "get_asr", "list_asr_providers", "register_asr"]
