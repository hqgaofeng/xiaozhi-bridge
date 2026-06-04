"""Tests for ASR and TTS abstractions."""

import os
import wave
from pathlib import Path

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


# --- V2 #1 (2026-06-04): sherpa-onnx end-to-end smoke (requires model) ---
#
# These tests load the real sherpa-onnx model and run actual inference on
# the bundled test_wavs. They are SKIPPED unless:
#   - /opt/xiaozhi-bridge/models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20
#     exists (production layout), OR
#   - XIAOZHI_TEST_MODEL_DIR env var points to a valid model dir
#
# In CI, these tests skip (no model available). Locally, Allen runs them.
# The model is NOT committed to the repo (~500MB).


_PROD_MODEL_DIR = Path(
    "/opt/xiaozhi-bridge/models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
)


def _resolve_test_model_dir():
    """Return Path to a real model dir, or None to skip."""
    env = os.environ.get("XIAOZHI_TEST_MODEL_DIR")
    candidates = [Path(env)] if env else []
    candidates.append(_PROD_MODEL_DIR)
    for p in candidates:
        if p and p.is_dir() and (p / "tokens.txt").is_file():
            return p
    return None


_MODEL_DIR = _resolve_test_model_dir()
_skip_no_model = pytest.mark.skipif(
    _MODEL_DIR is None,
    reason="sherpa-onnx model not available (set XIAOZHI_TEST_MODEL_DIR or install to /opt/xiaozhi-bridge/models/)",
)
_skip_no_sherpa = pytest.mark.skipif(
    pytest.importorskip("sherpa_onnx", minversion="1.10") is None,
    reason="sherpa-onnx>=1.10 not installed",
)


def _read_wav_int16(p: Path) -> tuple[bytes, int]:
    """Read a 16-bit mono wav file, return (raw_int16_bytes, sample_rate)."""
    with wave.open(str(p), "rb") as f:
        sr = f.getframerate()
        n = f.getnframes()
        return f.readframes(n), sr


@_skip_no_sherpa
@_skip_no_model
@pytest.mark.asyncio
async def test_asr_sherpa_onnx_transcribes_test_wav_0():
    """V2 #1: end-to-end on bundled test_wavs/0.wav (10s, zh+en mixed)."""
    assert _MODEL_DIR is not None  # for type checker
    wav = _MODEL_DIR / "test_wavs" / "0.wav"
    audio, sr = _read_wav_int16(wav)
    asr = get_asr("sherpa_onnx", options={"model_dir": str(_MODEL_DIR)})
    result = await asr.transcribe(audio, sample_rate=sr)
    # The bundled wav contains a Chinese+English mixed utterance
    # ("昨天是星期三" / "today is the day after tomorrow"). We only assert
    # non-empty (the exact text varies by audio decode + bpe subword).
    assert result.text, f"expected non-empty transcription, got {result.text!r}"
    assert result.language == "zh"


@_skip_no_sherpa
@_skip_no_model
@pytest.mark.asyncio
async def test_asr_sherpa_onnx_handles_empty_audio():
    """V2 #1: empty audio returns empty text without raising."""
    assert _MODEL_DIR is not None
    asr = get_asr("sherpa_onnx", options={"model_dir": str(_MODEL_DIR)})
    result = await asr.transcribe(b"", sample_rate=16000)
    assert result.text == ""


@_skip_no_sherpa
@_skip_no_model
@pytest.mark.asyncio
async def test_asr_sherpa_onnx_handles_short_audio():
    """V2 #1: very short audio (100ms of silence) returns text without error."""
    assert _MODEL_DIR is not None
    asr = get_asr("sherpa_onnx", options={"model_dir": str(_MODEL_DIR)})
    # 100ms of silence at 16kHz int16 mono = 1600 samples = 3200 bytes
    silence = b"\x00\x00" * 1600
    result = await asr.transcribe(silence, sample_rate=16000)
    # No assertion on text (could be empty or noise tokens), but must not raise.
    assert isinstance(result.text, str)


@_skip_no_sherpa
@_skip_no_model
@pytest.mark.asyncio
async def test_asr_sherpa_onnx_rejects_stereo_in_real_path():
    """V2 #1: stereo audio rejected (the skeleton test covers config;
    this covers the runtime path with a real recognizer loaded)."""
    assert _MODEL_DIR is not None
    asr = get_asr("sherpa_onnx", options={"model_dir": str(_MODEL_DIR)})
    # Force the recognizer to load (this is what we want to test the
    # runtime path of — not just the config-validation guard).
    asr._ensure_recognizer()
    with pytest.raises(ASRError, match="mono"):
        await asr.transcribe(b"\x00\x00" * 100, sample_rate=16000, channels=2)


@_skip_no_sherpa
@_skip_no_model
@pytest.mark.asyncio
async def test_asr_sherpa_onnx_resamples_8k_to_16k():
    """V2 #1: 8kHz audio works (sherpa-onnx does resampling internally)."""
    assert _MODEL_DIR is not None
    wav = _MODEL_DIR / "test_wavs" / "8k.wav"
    audio, sr = _read_wav_int16(wav)
    assert sr == 8000
    asr = get_asr("sherpa_onnx", options={"model_dir": str(_MODEL_DIR)})
    result = await asr.transcribe(audio, sample_rate=sr)
    # The 8k file has ~17s of Chinese speech. Even with bpe quirks the
    # output should be non-empty.
    assert result.text, f"expected non-empty text for 8k wav, got {result.text!r}"
