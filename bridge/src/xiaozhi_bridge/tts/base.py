"""TTS abstract base class and registry."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, AsyncIterator, Type


@dataclass
class TTSChunk:
    """A chunk of synthesized audio.

    - pcm: PCM int16 mono bytes at `sample_rate`.
    - text: The text that produced this chunk (for sentence_start events).
    - is_first: True if this is the first chunk of a new sentence.
    - is_last: True if this is the last chunk (synthesis complete).
    """

    pcm: bytes
    text: str
    sample_rate: int
    is_first: bool = False
    is_last: bool = False


class TTSBase(abc.ABC):
    """Abstract base for TTS providers.

    Implementations should yield TTSChunks in a streaming fashion so the
    server can begin playback before synthesis completes.
    """

    name: str = "base"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}

    @abc.abstractmethod
    async def synthesize_stream(
        self, text: str, sample_rate: int = 24000
    ) -> AsyncIterator[TTSChunk]:
        """Synthesize text → audio chunks.

        Args:
            text: Input text (usually a single sentence).
            sample_rate: Target output sample rate (e.g. 24000 for xiaozhi).

        Yields:
            TTSChunk instances. The first chunk should have is_first=True
            and the last should have is_last=True.
        """
        raise NotImplementedError
        yield  # Make this a generator for type checkers


class TTSError(Exception):
    """Raised when TTS synthesis fails."""


# --- Registry ---


_REGISTRY: dict[str, Type[TTSBase]] = {}


def register_tts(name: str):
    def decorator(cls: Type[TTSBase]) -> Type[TTSBase]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_tts(name: str, options: dict[str, Any] | None = None) -> TTSBase:
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "(none)"
        raise KeyError(f"Unknown TTS provider: {name!r}. Available: {available}")
    return _REGISTRY[name](options=options)


def list_tts_providers() -> list[str]:
    return sorted(_REGISTRY.keys())
