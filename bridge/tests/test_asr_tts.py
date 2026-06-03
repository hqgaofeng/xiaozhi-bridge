"""Tests for ASR and TTS abstractions."""

import pytest

from xiaozhi_bridge.asr import get_asr, list_asr_providers
from xiaozhi_bridge.tts import get_tts, list_tts_providers


def test_asr_registry_has_mock():
    assert "mock" in list_asr_providers()


def test_asr_mock_random():
    asr = get_asr("mock", {"mode": "random", "phrases": ["hello"]})
    assert asr.name == "mock"


def test_asr_unknown_provider_raises():
    with pytest.raises(KeyError, match="Unknown ASR provider"):
        get_asr("not_a_real_provider")


def test_tts_registry_has_mock():
    assert "mock" in list_tts_providers()


def test_tts_unknown_provider_raises():
    with pytest.raises(KeyError, match="Unknown TTS provider"):
        get_tts("not_a_real_provider")


@pytest.mark.asyncio
async def test_asr_mock_transcribe_returns_text():
    asr = get_asr("mock", {"mode": "fixed", "text": "测试文本"})
    result = await asr.transcribe(b"\x00\x00" * 1000, sample_rate=16000)
    assert result.text == "测试文本"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_tts_mock_stream_yields_chunks():
    tts = get_tts("mock", {"mode": "silence", "chunk_ms": 60})
    chunks = []
    async for chunk in tts.synthesize_stream("你好", sample_rate=24000):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert chunks[0].is_first is True
    assert chunks[-1].is_last is True
    assert chunks[0].sample_rate == 24000
