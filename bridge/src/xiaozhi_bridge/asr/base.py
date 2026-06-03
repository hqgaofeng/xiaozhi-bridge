"""ASR abstract base class and registry."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass
class ASRResult:
    """Result of an ASR transcription."""

    text: str
    confidence: float = 1.0
    # Optional: detected language (e.g. "zh", "en")
    language: str | None = None
    # Optional: timing info
    duration_ms: int | None = None
    # Raw provider response (for debugging)
    raw: dict[str, Any] | None = None


class ASRBase(abc.ABC):
    """Abstract base for ASR providers.

    Implementations should be safe to instantiate once and reuse across
    requests (they should be thread-safe or use async-native I/O).
    """

    # Subclasses set this in __init__ or as a class attribute
    name: str = "base"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}

    @abc.abstractmethod
    async def transcribe(
        self, audio: bytes, sample_rate: int, channels: int = 1
    ) -> ASRResult:
        """Transcribe audio bytes to text.

        Args:
            audio: PCM int16 mono bytes (after Opus decode).
            sample_rate: e.g. 16000.
            channels: 1 for mono.

        Returns:
            ASRResult with the transcribed text.

        Raises:
            ASRError: if transcription fails.
        """
        raise NotImplementedError


class ASRError(Exception):
    """Raised when ASR transcription fails."""


# --- Registry ---


_REGISTRY: dict[str, type[ASRBase]] = {}


def register_asr(name: str):
    """Decorator to register an ASR implementation.

    Usage:
        @register_asr("aliyun")
        class AliyunASR(ASRBase):
            ...
    """

    def decorator(cls: type[ASRBase]) -> type[ASRBase]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_asr(name: str, options: dict[str, Any] | None = None) -> ASRBase:
    """Instantiate an ASR provider by name.

    Raises KeyError if the provider is not registered.
    """
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "(none)"
        raise KeyError(f"Unknown ASR provider: {name!r}. Available: {available}")
    return _REGISTRY[name](options=options)


def list_asr_providers() -> list[str]:
    """List all registered ASR provider names."""
    return sorted(_REGISTRY.keys())
