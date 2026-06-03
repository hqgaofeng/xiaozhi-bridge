"""TTS (Text-to-Speech) abstraction."""

from . import mock  # noqa: F401
from .base import TTSBase, TTSChunk, get_tts, list_tts_providers, register_tts

__all__ = ["TTSBase", "TTSChunk", "get_tts", "list_tts_providers", "register_tts"]
