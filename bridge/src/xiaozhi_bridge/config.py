"""Configuration management for xiaozhi-bridge.

Loads YAML config and provides a typed settings object via Pydantic.
Environment variables override config file values (e.g. for secrets).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Section: Server ---


class ServerConfig(BaseSettings):
    """WebSocket server settings."""

    model_config = SettingsConfigDict(extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    # Path prefix for WebSocket (e.g. /xiaozhi/v1/)
    path: str = "/xiaozhi/v1/"
    # WebSocket max message size (10 MB default)
    max_message_size: int = 10 * 1024 * 1024
    # NOTE: cors_origins was removed in v0.1.5 — V1 ships a raw WebSocket
    # server (no CORS handshake; the browser-side web admin calls the
    # bridge's reverse-proxied /api/* via nginx, not direct cross-origin).
    # If you need it back for V2 (FastAPI), add it there, not here.


# --- Section: OpenClaw (LLM) ---


class OpenClawConfig(BaseSettings):
    """Connection to the openclaw gateway."""

    model_config = SettingsConfigDict(extra="ignore")

    base_url: str = "http://127.0.0.1:18789"
    api_key: str = ""  # Gateway auth token (Bearer)
    # Agent target. "openclaw" routes to the default agent; the actual
    # backend LLM is selected inside openclaw (and can be overridden via
    # the `x-openclaw-model` header or openclaw's own config).
    model: str = "openclaw"
    # Optional backend LLM override (sent as x-openclaw-model header).
    backend_model: str = ""
    # Stable per-caller session id; openclaw uses this to derive a
    # deterministic sessionKey and keep sessions isolated between
    # distinct callers (e.g. multiple ESP32 devices).
    user: str = "xiaozhi-bridge"
    session_key: str = ""
    # 是否流式响应
    stream: bool = True
    # 最大上下文 token
    max_tokens: int = 4096
    # 温度
    temperature: float = 0.7
    # 请求超时（秒）
    timeout: float = 60.0


# --- Section: ASR ---


class ASRConfig(BaseSettings):
    """Speech-to-text provider config (pluggable)."""

    model_config = SettingsConfigDict(extra="ignore")

    # Provider 名称，必须在 asr/ 下有对应实现
    # 可选: mock | aliyun | tencent | xfyun | ...
    provider: str = "mock"

    # 各 provider 私有配置（不验证，按 provider 自己读）
    options: dict = Field(default_factory=dict)


# --- Section: TTS ---


class TTSConfig(BaseSettings):
    """Text-to-speech provider config (pluggable)."""

    model_config = SettingsConfigDict(extra="ignore")

    # Provider 名称
    # 可选: mock | edge | sherpa_onnx | aliyun | ...
    provider: str = "mock"

    # 语音 ID（不同 provider 取值不同）
    voice: str = "zh-CN-XiaoxiaoNeural"
    # 语速
    rate: str = "+0%"
    # 音量
    volume: str = "+0%"

    options: dict = Field(default_factory=dict)


# --- Section: Device / Session ---


class DeviceConfig(BaseSettings):
    """Device and session settings."""

    model_config = SettingsConfigDict(extra="ignore")

    # Bearer token expected in Authorization header (optional)
    auth_token: str = ""
    # Session ID prefix
    session_id_prefix: str = "xiaozhi"
    # NOTE: echo_mode was removed in v0.1.5 — was a debug flag nobody wired
    # up. If you want a debug echo mode in V2, add it back and implement
    # it in server._process_text (skip the LLM round-trip).


# --- Section: MCP / IoT ---


class MCPConfig(BaseSettings):
    """MCP server settings (JSON-RPC 2.0 endpoint).

    V1: kept for compatibility but the server is always enabled and
    never auto-initializes against the device. The runtime always
    handles `type: "mcp"` messages if a device sends them.
    """

    model_config = SettingsConfigDict(extra="ignore")

    # NOTE: enabled / auto_initialize flags were removed in v0.1.5 —
    # they were defined but never read. The MCP server is always on
    # (it's the only way the device can call bridge-side tools).
    # V2 will need real config here (e.g. pagination cursors, per-session
    # tool ACLs, etc.) — add it then.


# --- Section: Logging ---


class LoggingConfig(BaseSettings):
    """Logging settings."""

    model_config = SettingsConfigDict(extra="ignore")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "console"] = "console"
    # 日志文件路径（None = 只输出到 stdout）
    file: str | None = None


# --- Root Config ---


class AppConfig(BaseSettings):
    """Root configuration for xiaozhi-bridge."""

    model_config = SettingsConfigDict(
        env_prefix="XIAOZHI_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    openclaw: OpenClawConfig = Field(default_factory=OpenClawConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    # MCP config kept in yaml for future V2 use; the runtime doesn't read
    # any of its fields right now (the server is always on).
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> AppConfig:
        """Load config from YAML file, then apply env overrides."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with path.open() as f:
            raw = yaml.safe_load(f) or {}

        # Map top-level keys to nested config
        return cls(**raw)

    def dump(self) -> dict:
        """Dump config to dict (for debugging)."""
        return self.model_dump()
