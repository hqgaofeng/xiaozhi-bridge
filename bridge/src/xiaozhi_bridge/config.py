"""Configuration management for xiaozhi-bridge.

Loads YAML config and provides a typed settings object via Pydantic.
Environment variables override config file values (e.g. for secrets).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


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
    # Allowed CORS origins for the web UI
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


# --- Section: OpenClaw (LLM) ---


class OpenClawConfig(BaseSettings):
    """Connection to the openclaw gateway."""

    model_config = SettingsConfigDict(extra="ignore")

    base_url: str = "http://127.0.0.1:18789"
    api_key: str = ""  # 默认通过 auth profile
    # 编码/对话使用的模型
    model: str = "minimax/MiniMax-M3"
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
    # Auto-reply for testing
    echo_mode: bool = False


# --- Section: MCP / IoT ---


class MCPConfig(BaseSettings):
    """MCP server settings (JSON-RPC 2.0 endpoint)."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = True
    # 是否在握手时自动发 initialize 请求
    auto_initialize: bool = True


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
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
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
