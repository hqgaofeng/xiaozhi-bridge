"""Tests for ASR and TTS abstractions."""

import pytest

from xiaozhi_bridge.asr import ASRError, get_asr, list_asr_providers
from xiaozhi_bridge.tts import TTSError, get_tts, list_tts_providers


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


# --- V2 #1 (2026-06-04): cloud provider skeletons (not-yet-implemented) ---


def test_asr_registry_includes_cloud_skeleton():
    """V2 #1 reserves 'cloud' provider name for future Aliyun/Tencent/etc."""
    assert "cloud" in list_asr_providers()


def test_tts_registry_includes_cloud_skeleton():
    """V2 #1 reserves 'cloud' provider name for future edge-tts/Aliyun/etc."""
    assert "cloud" in list_tts_providers()


def test_asr_cloud_skeleton_instantiates_without_vendor():
    """The cloud skeleton can be constructed even without `vendor` set.

    This is intentional — `list_asr_providers()` and config-validation
    paths should be able to enumerate/construct without raising.
    """
    asr = get_asr("cloud", options={})
    assert asr.name == "cloud"


def test_tts_cloud_skeleton_instantiates_without_vendor():
    tts = get_tts("cloud", options={})
    assert tts.name == "cloud"


@pytest.mark.asyncio
async def test_asr_cloud_skeleton_transcribe_raises():
    """V2 #1: cloud ASR is not implemented yet — must fail LOUDLY.

    Returning empty text would silently break the protocol. Raising
    ASRError makes misconfiguration visible in logs and e2e tests.
    """
    asr = get_asr("cloud", options={"vendor": "aliyun"})
    with pytest.raises(ASRError, match="not implemented"):
        await asr.transcribe(b"\x00\x00" * 100, sample_rate=16000)


@pytest.mark.asyncio
async def test_tts_cloud_skeleton_synthesize_raises():
    """V2 #1: cloud TTS is not implemented yet — must fail LOUDLY."""
    tts = get_tts("cloud", options={"vendor": "edge"})
    with pytest.raises(TTSError, match="not implemented"):
        # synthesize_stream is an async generator; consuming it triggers the raise.
        async for _ in tts.synthesize_stream("hello", sample_rate=24000):
            pass


# --- V2 #1 (2026-06-04): sherpa-onnx local ASR provider (skeleton) ---


def test_asr_registry_includes_sherpa_onnx():
    """V2 #1: sherpa-onnx is now a first-class registered provider."""
    assert "sherpa_onnx" in list_asr_providers()


def test_asr_sherpa_onnx_requires_model_dir():
    """V2 #1: misconfiguration (no model_dir) must fail loud at construct time."""
    with pytest.raises(ASRError, match="model_dir"):
        get_asr("sherpa_onnx", options={})


def test_asr_sherpa_onnx_constructs_with_model_dir():
    """V2 #1: providing model_dir succeeds (validates config only, lazy load)."""
    asr = get_asr("sherpa_onnx", options={"model_dir": "/nonexistent"})
    assert asr.name == "sherpa_onnx"
    assert asr.num_threads == 2  # default
    assert asr.decoding_method == "greedy_search"  # default
    assert asr.provider == "cpu"  # default


def test_asr_sherpa_onnx_custom_options():
    asr = get_asr(
        "sherpa_onnx",
        options={
            "model_dir": "/opt/x",
            "num_threads": 4,
            "decoding_method": "modified_beam_search",
        },
    )
    assert asr.num_threads == 4
    assert asr.decoding_method == "modified_beam_search"


@pytest.mark.asyncio
async def test_asr_sherpa_onnx_transcribe_rejects_stereo():
    """V2 #1: only mono is supported — fail loud instead of silent wrong text."""
    asr = get_asr("sherpa_onnx", options={"model_dir": "/nonexistent"})
    with pytest.raises(ASRError, match="mono"):
        await asr.transcribe(b"\x00\x00" * 100, sample_rate=16000, channels=2)


@pytest.mark.asyncio
async def test_asr_sherpa_onnx_transcribe_raises_when_model_dir_missing():
    """V2 #1: clear error when model_dir doesn't exist (not a stack trace)."""
    asr = get_asr("sherpa_onnx", options={"model_dir": "/no/such/dir/please"})
    with pytest.raises(ASRError, match="does not exist"):
        await asr.transcribe(b"\x00\x00" * 100, sample_rate=16000)
