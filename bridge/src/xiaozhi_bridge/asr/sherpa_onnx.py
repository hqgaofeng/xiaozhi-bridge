"""Sherpa-onnx ASR provider (V2 #1, 2026-06-04).

Local, offline speech recognition via [sherpa-onnx](https://k2-fsa.github.io/sherpa/onnx/).
No cloud credentials needed; runs entirely on CPU.

This is the **abstract skeleton** shipped in V2 #1. The concrete model
loader + recognizer binding is wired up in the follow-up steps
(see module-level ``TODO(V2 #1)`` markers).

Why sherpa-onnx?
- ONNX runtime: no PyTorch dependency, smaller image, faster cold start.
- Streaming Zipformer model: 200MB bilingual (zh+en), real-time on CPU.
- k2-fsa project: actively maintained, used in production voice assistants.
- End-to-end local: zero per-call cost, no API key leakage risk.

Configuration (config/config.yaml under ``asr:``):

    asr:
      provider: sherpa_onnx
      options:
        # Required: directory containing tokens.txt + encoder/decoder/joiner .onnx
        model_dir: /opt/xiaozhi-bridge/models/sherpa-onnx-streaming-zipformer-bilingual
        # Optional: number of threads for ONNX runtime (default 2)
        num_threads: 2
        # Optional: decoding method "greedy_search" (default) | "modified_beam_search"
        decoding_method: greedy_search
        # Optional: provider "cpu" (default) | "cuda" (not used in V2 #1)
        provider: cpu

Resource budget (VPS 1G RAM + 1G swap):
- Model load: ~200-300MB RSS spike, then settles at ~150-200MB.
- Inference: <0.3 RTF on a single modern x86 core.
- Lazy-loaded on first transcribe() call so the bridge starts fast.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import ASRBase, ASRError, ASRResult, register_asr

log = logging.getLogger(__name__)

# These are the files sherpa-onnx expects in the model directory.
# (For the streaming-zipformer-bilingual-zh-en-2023-02-20 model.)
_REQUIRED_MODEL_FILES = (
    "tokens.txt",
    "encoder-epoch-99-avg-1.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.onnx",
)


@register_asr("sherpa_onnx")
class SherpaOnnxASR(ASRBase):
    """Local ASR via sherpa-onnx streaming Zipformer (bilingual zh+en).

    V2 #1: skeleton with config validation and a clear error if the
    real model loader hasn't been wired up yet. The full implementation
    is added in the follow-up step (after pip install + model download).
    """

    name = "sherpa_onnx"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        # Note: Path('') normalises to PosixPath('.'), which is truthy,
        # so we must check the raw string (or the resulting Path) before
        # constructing the Path object. See test_asr_sherpa_onnx_requires_model_dir.
        raw_model_dir = self.options.get("model_dir") or ""
        self.model_dir = Path(raw_model_dir)
        self.num_threads = int(self.options.get("num_threads", 2))
        self.decoding_method = self.options.get("decoding_method", "greedy_search")
        self.provider = self.options.get("provider", "cpu")

        # Lazy recognizer handle (avoids paying model-load cost at import).
        self._recognizer: Any = None

        # Validate config eagerly — fail loud on misconfiguration
        # rather than waiting until the first user says "你好".
        if not raw_model_dir:
            raise ASRError(
                "sherpa_onnx ASR requires `asr.options.model_dir`. "
                "Set it in config.yaml to the directory containing "
                "tokens.txt + encoder/decoder/joiner .onnx files. "
                "See docs/config.md for the recommended host path."
            )

    def _ensure_model_files(self) -> None:
        """Raise ASRError with a clear message if any model file is missing."""
        if not self.model_dir.is_dir():
            raise ASRError(
                f"sherpa_onnx model_dir does not exist: {self.model_dir}. "
                f"Download the streaming-zipformer-bilingual-zh-en-2023-02-20 "
                f"model (or set model_dir to the correct path)."
            )
        missing = [f for f in _REQUIRED_MODEL_FILES if not (self.model_dir / f).is_file()]
        if missing:
            raise ASRError(
                f"sherpa_onnx model_dir is missing required files: {missing}. "
                f"Expected in: {self.model_dir}. "
                f"See docs/config.md for the download command."
            )

    def _ensure_recognizer(self) -> None:
        """Lazy-init the underlying sherpa_onnx.OnlineRecognizer.

        Kept out of __init__ so bridge startup stays fast and so tests
        can construct the provider without forcing the model load.
        """
        if self._recognizer is not None:
            return
        self._ensure_model_files()
        # The actual import + recognizer construction is wired in the
        # follow-up step (after sherpa-onnx is in pyproject + installed).
        # Today this raises a clear "not yet implemented" error.
        raise ASRError(
            "sherpa_onnx recognizer is not yet wired up in this build. "
            "V2 #1 ships the skeleton + config validation; the live "
            "model loader lands in the next commit (after pip install + "
            "model download). Use provider=mock in the meantime."
        )

    async def transcribe(
        self, audio: bytes, sample_rate: int, channels: int = 1
    ) -> ASRResult:
        """Transcribe PCM int16 mono bytes to text.

        V2 #1 skeleton: validates config + model files, then raises a
        clear "not yet implemented" error. The streaming recognition
        loop is added in the follow-up step.
        """
        if channels != 1:
            raise ASRError(
                f"sherpa_onnx ASR expects mono audio (channels=1), got {channels}"
            )
        self._ensure_recognizer()  # raises ASRError with a clear message
        # Unreachable until the recognizer is wired up; placeholder to
        # make the type checker happy.
        raise NotImplementedError("sherpa_onnx transcribe: see _ensure_recognizer")
