"""Mock ASR implementation for testing.

Returns a configurable text (or random pick from a list) regardless of input.
Useful for:
- Unit tests
- Local development without real ASR API keys
- Demonstrating the protocol end-to-end
"""

from __future__ import annotations

import random

from .base import ASRBase, ASRResult, register_asr


_MOCK_PHRASES_ZH = [
    "你好小智",
    "今天天气怎么样",
    "把灯打开",
    "把灯关掉",
    "现在几点了",
    "讲个笑话",
    "播放音乐",
    "提醒我明天下午三点开会",
]


@register_asr("mock")
class MockASR(ASRBase):
    """Returns mock text for any input audio.

    Configurable via options:
        - mode: "random" (default) | "fixed"
        - text: string (used if mode="fixed")
        - phrases: list of strings (used if mode="random")
        - latency_ms: simulated processing time
    """

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(options)
        self.mode = self.options.get("mode", "random")
        self.text = self.options.get("text", "你好小智")
        self.phrases = self.options.get("phrases", _MOCK_PHRASES_ZH)
        self.latency_ms = int(self.options.get("latency_ms", 100))

    async def transcribe(
        self, audio: bytes, sample_rate: int, channels: int = 1
    ) -> ASRResult:
        # Simulate processing time
        import asyncio

        await asyncio.sleep(self.latency_ms / 1000)

        # The audio parameter is intentionally unused — we mock the result.
        del audio, sample_rate, channels  # silence linters

        if self.mode == "fixed":
            text = self.text
        else:
            text = random.choice(self.phrases)

        return ASRResult(text=text, confidence=1.0, language="zh")
