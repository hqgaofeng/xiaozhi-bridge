# 配置说明

> xiaozhi-bridge 的所有可配置项

## 配置文件位置

- **开发**：`./config.yaml`（项目根目录）
- **生产**：`/root/projects/xiaozhi-bridge/config/config.yaml`
- **环境变量覆盖**：所有字段都支持 `XIAOZHI_<SECTION>__<FIELD>` 格式的环境变量

## 完整配置示例

参见 `config/config.example.yaml`。

## 配置项详解

### server

WebSocket 服务器配置。

```yaml
server:
  host: 0.0.0.0              # 监听地址
  port: 8000                  # 监听端口
  path: /xiaozhi/v1/          # WebSocket 路径（设备要连这个）
  max_message_size: 10485760  # 单消息最大字节数（10MB）
  cors_origins:               # CORS 白名单（智控台域名）
    - http://localhost:3000
```

### openclaw

OpenClaw gateway 连接配置（bridge 调宿主上跑的 openclaw）。

```yaml
openclaw:
  # 容器内调宿主上跑的 openclaw gateway
  # 从 bridge 容器看 host.docker.internal = docker bridge gateway IP (172.17.0.1)
  # 要求宿主 openclaw.json 里 gateway.bind != "loopback"（推荐 "lan" / "auto" / "custom"）
  base_url: http://host.docker.internal:18789
  # 从宿主 ~/.openclaw/openclaw.json 的 gateway.auth.token 拿
  # 空字符串 = 不传 Authorization（不推荐）
  api_key: "<gateway.auth.token>"
  # agent target 模式：固定填 "openclaw"（走 openclaw default agent）
  # 实际后端 LLM 由 openclaw 端 agent 配置决定
  model: openclaw
  # 可选：强制选后端 LLM（通过 x-openclaw-model header 传）
  # 例如 "minimax/MiniMax-M3-highspeed"。留空 = 走 openclaw agent 默认。
  backend_model: ""
  # 用户会话隔离：openclaw 从 user 派生 sessionKey，不同 user 互不串历史
  # "xiaozhi-bridge" 派生出的 sessionKey 跟主会话（agent:default-main:openai-user:8682984776）完全独立
  user: xiaozhi-bridge
  # 可选：显式 session key（跟 user 二选一）
  # session_key: ""
  stream: true
  max_tokens: 4096
  temperature: 0.7
  timeout: 60.0
```

**V1 明确不传**：
- `tools[]` — openclaw 自带 tool registry，外部传的 tools 会被拒绝
- `system` — 走 openclaw agent 自己的 system prompt（不在 bridge 里写）

### asr

ASR provider 配置（可插拔）。

```yaml
asr:
  provider: mock         # 当前：mock；可扩展：aliyun、tencent、xfyun
  options:               # 各 provider 私有配置
    # Mock 特定
    mode: random         # random | fixed
    text: "你好小智"     # fixed 模式返回的文本
    phrases:             # random 模式的语料
      - "今天天气怎么样"
      - "把灯打开"
    latency_ms: 100      # 模拟 ASR 延迟
```

### tts

TTS provider 配置（可插拔）。

```yaml
tts:
  provider: mock         # 当前：mock；可扩展：edge、sherpa_onnx
  voice: zh-CN-XiaoxiaoNeural   # 语音 ID
  rate: "+0%"                    # 语速
  volume: "+0%"                  # 音量
  options:
    mode: silence        # silence | tone
    chunk_ms: 60
```

### device

设备与会话管理。

```yaml
device:
  auth_token: ""         # 可选：设备的 Bearer token（留空 = 不校验）
  session_id_prefix: xiaozhi
  echo_mode: false       # 调试用：回声模式
```

### mcp

MCP 端点配置。

```yaml
mcp:
  enabled: true
  auto_initialize: true  # 握手后自动发 initialize 请求
```

### logging

日志配置。

```yaml
logging:
  level: INFO            # DEBUG | INFO | WARNING | ERROR
  format: console         # console | json
  file: null             # null = 只输出 stdout；或 /var/log/xiaozhi-bridge/bridge.log
```

## 添加新 Provider

### 添加新 ASR（如阿里云）

1. 创建文件 `bridge/src/xiaozhi_bridge/asr/aliyun.py`：

```python
from .base import ASRBase, ASRResult, register_asr

@register_asr("aliyun")
class AliyunASR(ASRBase):
    async def transcribe(self, audio: bytes, sample_rate: int, channels: int = 1) -> ASRResult:
        # 调用阿里云 SDK
        text = await self._call_aliyun(audio, sample_rate)
        return ASRResult(text=text)
    
    async def _call_aliyun(self, audio, sample_rate):
        # 实现...
        pass
```

2. 在 `bridge/src/xiaozhi_bridge/asr/__init__.py` 添加 import：

```python
from . import aliyun  # noqa: F401
```

3. 在 `config/config.yaml` 设置：

```yaml
asr:
  provider: aliyun
  options:
    ak_id: YOUR_AK_ID
    ak_secret: YOUR_AK_SECRET
    app_key: YOUR_APP_KEY
```

TTS / LLM 同样流程。

## 环境变量覆盖

所有字段都支持环境变量，格式：`XIAOZHI_<SECTION>__<FIELD>`

```bash
# 例子：把日志级别改为 DEBUG
export XIAOZHI_LOGGING__LEVEL=DEBUG

# 例子：切换 ASR provider
export XIAOZHI_ASR__PROVIDER=aliyun
export XIAOZHI_ASR__OPTIONS__AK_ID=xxx
```

注意双下划线 `__` 表示嵌套。
