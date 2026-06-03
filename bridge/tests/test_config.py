"""Tests for config loading."""

from pathlib import Path

import pytest

from xiaozhi_bridge.config import AppConfig


def test_default_config():
    config = AppConfig()
    assert config.server.host == "0.0.0.0"
    assert config.server.port == 8000
    assert config.asr.provider == "mock"
    assert config.tts.provider == "mock"
    assert config.openclaw.model == "openclaw"


def test_config_from_yaml(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
server:
  port: 9000
  host: 127.0.0.1
asr:
  provider: aliyun
  options:
    ak_id: test
tts:
  provider: edge
  voice: zh-CN-YunxiNeural
""")
    config = AppConfig.from_yaml(config_file)
    assert config.server.port == 9000
    assert config.server.host == "127.0.0.1"
    assert config.asr.provider == "aliyun"
    assert config.asr.options["ak_id"] == "test"
    assert config.tts.voice == "zh-CN-YunxiNeural"


def test_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        AppConfig.from_yaml("/nonexistent/config.yaml")
