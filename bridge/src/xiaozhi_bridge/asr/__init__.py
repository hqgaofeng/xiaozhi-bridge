"""ASR (Automatic Speech Recognition) abstraction.

Define a common interface and a registry, so users can swap providers
(Aliyun, Tencent, Xunfei, local Whisper, etc.) via config.
"""

from .base import ASRBase, ASRResult, register_asr, get_asr, list_asr_providers
from . import mock  # noqa: F401  (registers MockASR)

__all__ = ["ASRBase", "ASRResult", "register_asr", "get_asr", "list_asr_providers"]
