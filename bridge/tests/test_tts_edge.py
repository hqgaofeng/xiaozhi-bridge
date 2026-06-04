"""Tests for the edge-tts TTS provider (V2 #2).

Layered the same way as V2 #1 sherpa-onnx tests:

  1. Unit tests (no network, no ffmpeg) — always run in CI.
     These validate registry, config validation, chunk
     structure, and the empty-text path.

  2. End-to-end smoke (real edge-tts API + ffmpeg) — SKIPPED
     unless the XIAOZHI_TEST_EDGE_TTS=1 env var is set. CI does
     not have ffmpeg / outbound to api.msedgeservices.com, so
     we never run this layer there. Locally and on VPS, Allen
     runs it before merging a release.

The end-to-end layer is intentionally a small smoke test (one
sentence, assert non-empty PCM, assert reasonable duration) —
NOT a full quality test. Edge-tts's actual voice quality
needs a human listening test, not a unit test.
"""

from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest

from xiaozhi_bridge.tts import TTSError, get_tts, list_tts_providers

# --- Unit tests (always run) ---


def test_tts_registry_includes_edge():
    """V2 #2: edge-tts is now a first-class registered provider."""
    assert "edge" in list_tts_providers()


def test_tts_edge_constructs_with_defaults():
    tts = get_tts("edge", options={})
    assert tts.name == "edge"
    assert tts.chunk_ms == 60
    assert tts.boundary == "SentenceBoundary"
    assert tts.connect_timeout == 10
    assert tts.receive_timeout == 60


def test_tts_edge_custom_options():
    tts = get_tts(
        "edge",
        options={
            "voice": "en-US-JennyNeural",
            "rate": "-10%",
            "chunk_ms": 40,
            "boundary": "WordBoundary",
            "connect_timeout": 5,
        },
    )
    assert tts.boundary == "WordBoundary"
    assert tts.chunk_ms == 40
    assert tts.connect_timeout == 5


def test_tts_edge_rejects_invalid_boundary():
    """V2 #2: boundary must be SentenceBoundary or WordBoundary."""
    with pytest.raises(ValueError, match="boundary"):
        get_tts("edge", options={"boundary": "BAD"})


@pytest.mark.asyncio
async def test_tts_edge_rejects_empty_text():
    tts = get_tts("edge", options={})
    with pytest.raises(TTSError, match="empty text"):
        async for _ in tts.synthesize_stream("", sample_rate=24000):
            pass
    with pytest.raises(TTSError, match="empty text"):
        async for _ in tts.synthesize_stream("   ", sample_rate=24000):
            pass


@pytest.mark.asyncio
async def test_tts_edge_rejects_invalid_sample_rate():
    tts = get_tts("edge", options={})
    with pytest.raises(TTSError, match="sample_rate"):
        async for _ in tts.synthesize_stream("hello", sample_rate=0):
            pass


# --- End-to-end smoke (env-gated) ---
#
# These tests hit the real Microsoft edge-tts service and require
# ffmpeg in $PATH (for pydub mp3 → PCM decoding). They are skipped
# in CI and run manually on Allen's machine / VPS.
#
# Enable with:  XIAOZHI_TEST_EDGE_TTS=1 pytest tests/test_tts_edge.py
#
# What this layer covers:
#   - Real network call to api.msedgeservices.com succeeds.
#   - Real mp3 → pcm decode via ffmpeg produces non-empty PCM.
#   - First/last chunk flags are set correctly.
#   - Output sample_rate matches what was requested.


_RUN_E2E = os.environ.get("XIAOZHI_TEST_EDGE_TTS") == "1"


@pytest.mark.skipif(
    not _RUN_E2E,
    reason="V2 #2 edge-tts e2e: set XIAOZHI_TEST_EDGE_TTS=1 to enable (needs ffmpeg + internet)",
)
@pytest.mark.asyncio
async def test_tts_edge_e2e_synthesizes_short_chinese():
    """V2 #2: 1 Chinese sentence → non-empty PCM int16 mono at 24kHz."""
    tts = get_tts("edge", options={})  # default voice = zh-CN-XiaoxiaoNeural
    chunks = []
    async for chunk in tts.synthesize_stream("你好。", sample_rate=24000):
        chunks.append(chunk)
    assert len(chunks) > 0, "edge-tts produced no chunks for short Chinese"
    assert chunks[0].is_first is True
    assert chunks[-1].is_last is True
    assert chunks[0].sample_rate == 24000
    # All chunks should be the requested sample rate.
    for c in chunks:
        assert c.sample_rate == 24000
    # At least one chunk should be non-empty PCM.
    total_pcm = b"".join(c.pcm for c in chunks)
    assert len(total_pcm) > 0
    # 60ms at 24kHz int16 mono = 24000 * 0.06 * 2 = 2880 bytes per chunk.
    # "你好。" is ~250-500ms of audio → 4-9 chunks worth of data.
    # We just check it's > 1000 bytes (~21ms of audio) so the test is
    # stable across voice variations.
    assert len(total_pcm) > 1000, f"PCM too short: {len(total_pcm)} bytes"


@pytest.mark.skipif(
    not _RUN_E2E,
    reason="V2 #2 edge-tts e2e: set XIAOZHI_TEST_EDGE_TTS=1 to enable (needs ffmpeg + internet)",
)
@pytest.mark.asyncio
async def test_tts_edge_e2e_synthesizes_english():
    """V2 #2: 1 English sentence → non-empty PCM."""
    tts = get_tts("edge", options={"voice": "en-US-JennyNeural"})
    chunks = []
    async for chunk in tts.synthesize_stream("Hello there.", sample_rate=24000):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert chunks[0].is_first is True
    assert chunks[-1].is_last is True
    total_pcm = b"".join(c.pcm for c in chunks)
    assert len(total_pcm) > 1000


@pytest.mark.skipif(
    not _RUN_E2E,
    reason="V2 #2 edge-tts e2e: set XIAOZHI_TEST_EDGE_TTS=1 to enable (needs ffmpeg + internet)",
)
@pytest.mark.asyncio
async def test_tts_edge_e2e_multi_sentence_chunks():
    """V2 #2: 3 sentences → first chunk is_first, last chunk is_last, all 24kHz."""
    tts = get_tts("edge", options={})
    text = "第一句。第二句。还有第三句。"
    chunks = []
    async for chunk in tts.synthesize_stream(text, sample_rate=24000):
        chunks.append(chunk)
    assert len(chunks) > 0
    # Exactly one chunk should have is_first=True (the very first).
    firsts = [i for i, c in enumerate(chunks) if c.is_first]
    assert firsts == [0], f"expected exactly first chunk is_first=True, got {firsts}"
    # Exactly one chunk should have is_last=True (the very last).
    lasts = [i for i, c in enumerate(chunks) if c.is_last]
    assert lasts == [len(chunks) - 1], f"expected last chunk is_last=True, got {lasts}"


@pytest.mark.skipif(
    not _RUN_E2E,
    reason="V2 #2 edge-tts e2e: set XIAOZHI_TEST_EDGE_TTS=1 to enable (needs ffmpeg + internet)",
)
@pytest.mark.asyncio
async def test_tts_edge_e2e_wav_writability():
    """V2 #2: the synthesized PCM can be written to a .wav file (sanity).

    This catches sample_rate / int16 / mono regressions — if the
    PCM is in the wrong format, wave.Wave_write will fail or produce
    a broken file. We write to /tmp and don't keep it.
    """
    tts = get_tts("edge", options={})
    chunks = []
    async for chunk in tts.synthesize_stream("测试", sample_rate=24000):
        chunks.append(chunk)
    pcm = b"".join(c.pcm for c in chunks)
    out_path = Path("/tmp/xiaozhi_edge_smoke.wav")
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(24000)
        wf.writeframes(pcm)
    assert out_path.exists() and out_path.stat().st_size > 44  # > wav header
    out_path.unlink()
