# bridge

> Python 桥接服务：连接 xiaozhi-esp32 设备与 openclaw gateway

## 角色

- **协议层**：实现 xiaozhi WebSocket 协议（握手、消息路由、Opus 音频）
- **抽象层**：ASR / TTS / LLM 都做成可插拔接口
- **编排层**：串联一次对话（ASR → LLM → TTS）

## 架构

```
设备 (WebSocket)
    ↓
[server.py]      ← WebSocket server, 设备连接入口
    ↓
[protocol/]      ← 消息解析/序列化, 状态机
    ↓
[asr/] [tts/] [llm/]   ← 可插拔实现
    ↓
[openclaw gateway :18789]   ← LLM 推理
```

## 快速开始

### 安装

```bash
# 推荐用 uv（更快）
uv sync

# 或者 pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 配置

```bash
cp ../config/config.example.yaml config.yaml
# 编辑 config.yaml，填入你的 ASR/TTS/openclaw 信息
```

### 启动

```bash
# 开发模式
python -m xiaozhi_bridge --config config.yaml

# 或用脚本
xiaozhi-bridge --config config.yaml
```

### 测试

```bash
pytest
```

## 模块说明

| 模块 | 职责 |
|---|---|
| `main.py` | 入口，初始化 |
| `config.py` | 配置加载（Pydantic） |
| `server.py` | WebSocket server 主体 |
| `protocol/messages.py` | 消息类型定义 |
| `protocol/audio.py` | Opus 音频处理 |
| `protocol/states.py` | 设备会话状态机 |
| `asr/base.py` | ASR 抽象接口 + 注册表 |
| `asr/mock.py` | Mock 实现（测试用） |
| `tts/base.py` | TTS 抽象接口 + 注册表 |
| `tts/mock.py` | Mock 实现 |
| `llm/openclaw.py` | 调用 openclaw HTTP API |
| `llm/prompts.py` | 系统 prompt 模板 |
| `mcp/server.py` | MCP JSON-RPC 2.0 端点 |
| `mcp/tools.py` | 工具注册表 |
| `utils/logging.py` | 结构化日志 |

## 扩展新 ASR / TTS

### 添加新 ASR 实现

1. 在 `asr/` 下创建新文件，如 `asr/aliyun.py`：

```python
from .base import ASRBase, register_asr

@register_asr("aliyun")
class AliyunASR(ASRBase):
    async def transcribe(self, audio: bytes, sample_rate: int) -> str:
        # 调用阿里云 API
        ...
        return "识别结果"
```

2. 在 `config.yaml` 设置 `asr.provider: aliyun`

3. 重启服务即可

类似方式添加 TTS / LLM。

## 协议文档

- xiaozhi 协议：[../docs/protocol.md](../docs/protocol.md)
- 系统架构：[../docs/architecture.md](../docs/architecture.md)
