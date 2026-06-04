"""TTS (Text-to-Speech) abstraction.

Define a common interface and a registry, so users can swap providers
(edge-tts, Aliyun SAMI, Volcengine, GPT-SoVITS, etc.) via config.

Registered providers (V2 #1, 2026-06-04):
  - mock   — silence or 440Hz tone, sized by input text length
  - cloud  — skeleton for edge/aliyun_tts/volcengine_tts/gpt_sovits. NOT YET IMPLEMENTED.
"""

from . import cloud, mock  # noqa: F401
from .base import (
    TTSBase,
    TTSChunk,
    TTSError,
    get_tts,
    list_tts_providers,
    register_tts,
)

__all__ = [
    "TTSBase",
    "TTSChunk",
    "TTSError",
    "get_tts",
    "list_tts_providers",
    "register_tts",
]
