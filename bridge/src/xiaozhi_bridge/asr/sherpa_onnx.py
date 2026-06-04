"""Sherpa-onnx ASR provider (V2 #1, 2026-06-04).

Local, offline speech recognition via [sherpa-onnx](https://k2-fsa.github.io/sherpa/onnx/).
No cloud credentials needed; runs entirely on CPU.

This module wires up the real :class:`sherpa_onnx.OnlineRecognizer` for
the streaming-zipformer-bilingual-zh-en model. It also stays
backward-compatible with the V2 #1 skeleton contract (config validation
at construct, lazy model load on first transcribe).

Configuration (config/config.yaml under ``asr:``):

    asr:
      provider: sherpa_onnx
      options:
        # Required: directory containing tokens.txt + encoder/decoder/joiner .onnx
        # (plus bpe.vocab for the streaming-zipformer-bilingual-zh-en model)
        model_dir: /opt/xiaozhi-bridge/models/sherpa-onnx-streaming-zipformer-bilingual
        # Optional: number of threads for ONNX runtime (default 2)
        num_threads: 2
        # Optional: decoding method "greedy_search" (default) | "modified_beam_search"
        decoding_method: greedy_search
        # Optional: ONNX runtime provider "cpu" (default) | "cuda" (V2 #1 = cpu)
        provider: cpu
        # Optional: modeling unit (REQUIRED for streaming-zipformer-bilingual).
        # The shipped model uses bpe; the default "cjkchar" produces empty text.
        # Set this in config.yaml; we read it from options if present.
        modeling_unit: bpe
        # Optional: bpe_vocab is auto-detected from model_dir/bpe.vocab if not set.

Resource budget (VPS 1G RAM + 1G swap):
- fp32 model: ~500MB disk, ~300-400MB RSS spike on load, settles at ~200MB.
- int8 model: ~200MB disk, ~100-150MB RSS spike.
- Inference: <0.3 RTF on a single x86 core.
- Lazy-loaded on first transcribe() call (fast bridge startup).

Pitfalls we hit during V2 #1 development (and now document):
1. ``accept_waveform`` expects float32 samples in [-1, 1], NOT int16.
   The bridge's upstream code already passes int16 PCM bytes (after
   Opus decode), so we convert here.
2. ``modeling_unit`` defaults to "cjkchar", but the bilingual model is
   bpe-trained. Forgetting this silently produces empty text — no
   error, no warning. We default it to "bpe" but allow override.
3. Decoding is pull-based: after accept_waveform + input_finished,
   you must loop ``is_ready + decode_stream`` until ``is_ready`` is
   False, THEN call get_result.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger
from .base import ASRBase, ASRError, ASRResult, register_asr

log = get_logger(__name__)

# Files we look for in model_dir. The "fp32" / "int8" suffixes reflect
# the two precisions sherpa-onnx ships for this model. We auto-detect
# int8 first (saves ~200MB on disk + memory) and fall back to fp32.
_MODEL_FILE_GROUPS = {
    "fp32": (
        "encoder-epoch-99-avg-1.onnx",
        "decoder-epoch-99-avg-1.onnx",
        "joiner-epoch-99-avg-1.onnx",
    ),
    "int8": (
        "encoder-epoch-99-avg-1.int8.onnx",
        "decoder-epoch-99-avg-1.int8.onnx",
        "joiner-epoch-99-avg-1.int8.onnx",
    ),
}
_REQUIRED_TOKENS_FILE = "tokens.txt"
_OPTIONAL_BPE_VOCAB = "bpe.vocab"


def _detect_model_precision(model_dir: Path) -> tuple[str, dict[str, Path]]:
    """Pick the best precision available in model_dir.

    Prefers int8 (smaller, faster, good enough for our usage). Falls
    back to fp32 if int8 files are missing. Returns (precision_label,
    {role: file_path}) where role is one of "encoder"/"decoder"/"joiner".
    """
    int8_paths = {role: model_dir / fname for role, fname in zip(
        ("encoder", "decoder", "joiner"), _MODEL_FILE_GROUPS["int8"], strict=False
    )}
    if all(p.is_file() for p in int8_paths.values()):
        return "int8", int8_paths

    fp32_paths = {role: model_dir / fname for role, fname in zip(
        ("encoder", "decoder", "joiner"), _MODEL_FILE_GROUPS["fp32"], strict=False
    )}
    if all(p.is_file() for p in fp32_paths.values()):
        return "fp32", fp32_paths

    # Build a clear error message listing what's missing.
    missing_int8 = [p.name for p in int8_paths.values() if not p.is_file()]
    missing_fp32 = [p.name for p in fp32_paths.values() if not p.is_file()]
    raise ASRError(
        f"sherpa_onnx model_dir missing required onnx files.\n"
        f"  int8 missing: {missing_int8 or 'OK'}\n"
        f"  fp32 missing: {missing_fp32 or 'OK'}\n"
        f"  model_dir: {model_dir}\n"
        f"  See docs/config.md for the download command."
    )


@register_asr("sherpa_onnx")
class SherpaOnnxASR(ASRBase):
    """Local ASR via sherpa-onnx streaming Zipformer (bilingual zh+en).

    V2 #1: real implementation backed by sherpa_onnx.OnlineRecognizer.
    Supports both fp32 and int8 model precisions (auto-detected).
    """

    name = "sherpa_onnx"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        # Path('') normalises to PosixPath('.'), so check the raw string first.
        raw_model_dir = self.options.get("model_dir") or ""
        self.model_dir = Path(raw_model_dir)
        self.num_threads = int(self.options.get("num_threads", 2))
        self.decoding_method = self.options.get("decoding_method", "greedy_search")
        self.provider = self.options.get("provider", "cpu")
        # modeling_unit: bilingual-zh-en is bpe; default to bpe (see module
        # docstring pitfall #2). Override to "cjkchar" only if you swap
        # to a different model family.
        self.modeling_unit = self.options.get("modeling_unit", "bpe")
        # Optional explicit bpe_vocab path; auto-detected from model_dir
        # if not set.
        self.bpe_vocab: Path | None = None
        raw_bpe = self.options.get("bpe_vocab")
        if raw_bpe:
            self.bpe_vocab = Path(raw_bpe)

        # Lazy recognizer handle (avoids paying model-load cost at import).
        self._recognizer: Any = None
        # Cached precision so the log message on first load isn't wrong.
        self._precision: str | None = None

        # Validate config eagerly — fail loud on misconfiguration.
        if not raw_model_dir:
            raise ASRError(
                "sherpa_onnx ASR requires `asr.options.model_dir`. "
                "Set it in config.yaml to the directory containing "
                "tokens.txt + encoder/decoder/joiner .onnx files."
            )

    def _resolve_model_files(self) -> tuple[str, dict[str, Path]]:
        """Validate model_dir and return (precision, {role: path})."""
        if not self.model_dir.is_dir():
            raise ASRError(
                f"sherpa_onnx model_dir does not exist: {self.model_dir}. "
                f"Download the streaming-zipformer-bilingual-zh-en-2023-02-20 "
                f"model (or set model_dir to the correct path)."
            )
        tokens_path = self.model_dir / _REQUIRED_TOKENS_FILE
        if not tokens_path.is_file():
            raise ASRError(
                f"sherpa_onnx model_dir is missing {_REQUIRED_TOKENS_FILE}: "
                f"{tokens_path}"
            )
        # bpe.vocab is required when modeling_unit=bpe
        if self.modeling_unit == "bpe":
            bpe = self.bpe_vocab or (self.model_dir / _OPTIONAL_BPE_VOCAB)
            if not bpe.is_file():
                raise ASRError(
                    f"sherpa_onnx with modeling_unit='bpe' requires bpe.vocab. "
                    f"Expected at: {bpe}. "
                    f"Set asr.options.bpe_vocab explicitly or place the file "
                    f"in model_dir."
                )
            self.bpe_vocab = bpe
        return _detect_model_precision(self.model_dir)

    def _ensure_recognizer(self) -> None:
        """Lazy-init the underlying sherpa_onnx.OnlineRecognizer.

        Imports sherpa_onnx inside the method so the module loads
        quickly when the provider isn't actually used (e.g. tests of
        other providers, or production with provider=mock).
        """
        if self._recognizer is not None:
            return
        precision, paths = self._resolve_model_files()
        # Local import — keeps sherpa-onnx out of the import path when
        # another ASR provider is configured.
        import sherpa_onnx

        kwargs: dict[str, Any] = {
            "tokens": str(self.model_dir / _REQUIRED_TOKENS_FILE),
            "encoder": str(paths["encoder"]),
            "decoder": str(paths["decoder"]),
            "joiner": str(paths["joiner"]),
            "num_threads": self.num_threads,
            "decoding_method": self.decoding_method,
            "provider": self.provider,
        }
        # Only pass modeling_unit + bpe_vocab if we're using bpe; sherpa-onnx
        # treats an empty bpe_vocab as a different code path that errored
        # in our smoke test.
        if self.modeling_unit == "bpe":
            assert self.bpe_vocab is not None  # _resolve_model_files guarantees
            kwargs["modeling_unit"] = "bpe"
            kwargs["bpe_vocab"] = str(self.bpe_vocab)

        log.info(
            "sherpa_onnx loading model (precision=%s, threads=%d, decoding=%s)",
            precision,
            self.num_threads,
            self.decoding_method,
        )
        load_started = time.monotonic()
        self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**kwargs)
        self._precision = precision
        load_ms = (time.monotonic() - load_started) * 1000
        log.info(
            "sherpa_onnx model ready",
            precision=precision,
            load_ms=round(load_ms, 1),
        )

    async def transcribe(
        self, audio: bytes, sample_rate: int, channels: int = 1
    ) -> ASRResult:
        """Transcribe PCM int16 mono bytes to text.

        Args:
            audio: PCM int16 mono bytes (after Opus decode). The bridge's
                server.py feeds raw int16 from the xiaozhi protocol.
            sample_rate: e.g. 16000 (or 8000 — sherpa-onnx will resample).
            channels: 1 for mono. Stereo raises ASRError (sherpa-onnx is
                mono-only).

        Returns:
            ASRResult with the transcribed text. ``confidence`` and
            ``duration_ms`` are best-effort (sherpa-onnx doesn't expose
            token-level confidence in the streaming API; we default to 1.0).
        """
        if channels != 1:
            raise ASRError(
                f"sherpa_onnx ASR expects mono audio (channels=1), got {channels}"
            )
        if not audio:
            return ASRResult(text="", confidence=0.0, language="zh")

        self._ensure_recognizer()
        assert self._recognizer is not None

        # Convert int16 PCM bytes → float32 samples in [-1, 1].
        # Pitfall #1 (see module docstring): sherpa_onnx.OnlineStream
        # .accept_waveform expects normalized float, not raw int16.
        n_samples = len(audio) // 2
        if n_samples == 0:
            return ASRResult(text="", confidence=0.0, language="zh")
        float_samples = [
            s / 32768.0 for s in struct.unpack(f"<{n_samples}h", audio)
        ]

        # Streaming decode loop.
        # Pitfall #3 (see module docstring): accept_waveform is non-blocking;
        # we must pull results via decode_stream until is_ready returns False.
        transcribe_started = time.monotonic()
        stream = self._recognizer.create_stream()
        stream.accept_waveform(float(sample_rate), float_samples)
        stream.input_finished()
        # Bound the loop to avoid pathological infinite loops on bad audio.
        for _ in range(10_000):
            if not self._recognizer.is_ready(stream):
                break
            self._recognizer.decode_stream(stream)
        result = self._recognizer.get_result_all(stream)
        text = (result.text or "").strip()
        transcribe_ms = (time.monotonic() - transcribe_started) * 1000
        audio_duration_ms = int(n_samples / sample_rate * 1000)

        # Log every transcribe so we can spot regressions / slow
        # inference in production. The text length is bounded for
        # log volume control — sherpa can output up to a few hundred
        # characters, but we don't want to dump 10kB into stdout.
        log.info(
            "sherpa_onnx transcribed",
            audio_duration_ms=audio_duration_ms,
            transcribe_ms=round(transcribe_ms, 1),
            rtf=round(transcribe_ms / max(audio_duration_ms, 1), 3),
            text_len=len(text),
            text_preview=text[:40] if text else "",
        )

        return ASRResult(
            text=text,
            confidence=1.0,  # sherpa_onnx streaming doesn't expose per-token conf
            language="zh",  # bilingual model is zh+en; default to zh
            duration_ms=audio_duration_ms,
        )
