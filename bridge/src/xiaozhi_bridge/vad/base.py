"""Base class for server-side VAD providers.

Mirrors xiaozhi-esp32-server/core/providers/vad/base.py — a thin ABC with
one method, is_vad(), that returns whether the audio frame contains voice.
"""

from abc import ABC, abstractmethod
from typing import Any


class VADProviderBase(ABC):
    """Abstract base for VAD providers (server-side voice activity detection)."""

    @abstractmethod
    def is_vad(self, conn: Any, opus_packet: bytes) -> bool:
        """Return True if the audio frame contains voice.

        Args:
            conn: The connection/session object. The provider may attach
                per-connection state (decoder buffers, ONNX state, etc.)
                to this object.
            opus_packet: A single Opus-encoded audio packet from the client.
                For Silero VAD, this is decoded to PCM internally.

        Returns:
            True if voice detected, False otherwise.
        """
        raise NotImplementedError
