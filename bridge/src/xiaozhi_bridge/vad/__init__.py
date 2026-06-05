"""Server-side Voice Activity Detection (VAD) for xiaozhi-bridge.

V2 #8.3: Bridge needs server-side VAD because ESP32's WebRTC VAD (mode 0,
aggressive) often does NOT trigger voice_stop in noisy environments,
leaving the device stuck in listening state.

Design follows the official xiaozhi-esp32-server SileroVAD implementation:
- Per-connection state (decoder + ONNX state + context + window)
- Sliding window (3 frames) + dual threshold (0.5 high, 0.2 low) + hysteresis
- 1000ms silence threshold for voice_stop

Why Silero VAD onnx (not webrtcvad):
- 2.3MB onnx model, lightweight
- Robust to background noise (webrtcvad was tested in 2013, Silero is 2024)
- Aligned with official xiaozhi-esp32-server design

See: xiaozhi-esp32-server/core/providers/vad/silero.py
"""

from xiaozhi_bridge.vad.base import VADProviderBase
from xiaozhi_bridge.vad.silero import SileroVADProvider

__all__ = ["SileroVADProvider", "VADProviderBase"]
