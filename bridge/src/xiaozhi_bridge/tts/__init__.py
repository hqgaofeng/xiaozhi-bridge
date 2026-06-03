"""TTS (Text-to-Speech) abstraction."""

from .base import TTSBase, TTSChunk, register_tts, get_tts, list_tts_providers
from . import mock  # noqa: F401

__all__ = ["TTSBase", "TTSChunk", "register_tts", "get_tts", "list_tts_providers"]
