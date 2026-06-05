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

可选 provider（v0.2.2）：

| 名称 | 说明 | 状态 |
|---|---|---|
| `mock` | 返固定/随机文本 | V1 |
| `sherpa_onnx` | 本地 ONNX streaming Zipformer (双语 zh+en)，CPU 推理 | V2 #1（v0.2.10 前默认） |
| `sensevoice` | 本地 ONNX 离线 SenseVoice (5 语种 zh+en+ja+ko+yue)，CPU 推理 | **V2 #10（v0.2.10+ 默认）** |
| `cloud` | 云 API 骨架（Aliyun/Tencent/iFlytek/Volcengine） | 未实现（V2 #X） |

```yaml
# V2 #10 默认（v0.2.10+）
asr:
  provider: sensevoice
  options:
    # sensevoice 必填：模型目录
    # 需含 model.int8.onnx（228MB） + tokens.txt（308KB）
    model_dir: /opt/xiaozhi-bridge/models/sensevoice-zh-en-ja-ko-yue-int8-2024-07-17
    # 可选（默认见括号）：
    # num_threads: 2         # ONNX runtime 线程数
    # language: auto         # auto | zh | en | ja | ko | yue
    # use_itn: true          # 开启后输出带标点 + 数字格式化
    # provider: cpu          # ONNX runtime provider（cuda 预留 V3+）

# V2 #1 退路：短句 < 10s + 低延迟场景
# asr:
#   provider: sherpa_onnx
#   options:
#     # sherpa_onnx 必填：模型目录
#     # 需含 tokens.txt + encoder/decoder/joiner .onnx（fp32 或 int8 都可）
#     # + bpe.vocab（bpe 训练的模型必需要）
#     model_dir: /opt/xiaozhi-bridge/models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20
#     # 可选（默认见括号）：
#     # num_threads: 2         # ONNX runtime 线程数
#     # decoding_method: greedy_search  # 或 modified_beam_search（C-1 边际改进）
#     # provider: cpu          # ONNX runtime provider（cuda 预留 V3+）
#     # modeling_unit: bpe     # 该模型是 bpe 训练，默认已为 bpe
#     # bpe_vocab: ...         # 不设则自动从 model_dir/bpe.vocab 读
```

> **V2 #1 资源预算**（VPS 1G RAM + 1G swap，sherpa_onnx）：
> - fp32 模型：加载 3.6s，稳态 ~150-200MB RSS，RTF ~0.43
> - int8 模型：加载更快，RSS 更低，默认自动选 int8
> - docker compose bridge 容器 mem_limit 已从 200m 调为 500m
>
> **V2 #10 资源预算**（sensevoice）：
> - int8 模型：~250-300MB RSS，RTF 0.2-0.3，**长句（> 15s）0 乱码**
> - 5 语种（zh/en/ja/ko/yue）支持，比 sherpa_onnx 强 3 倍
> - **VPS prod 实测**：12 段 wav（5 语种 + 4.7-30s 长度）全 0 乱码

```yaml
# 退路：虚抑 ASR（不加载模型，占位用）
asr:
  provider: mock
  options:
    mode: random
    text: "你好小智"
    phrases:
      - "今天天气怎么样"
      - "把灯打开"
    latency_ms: 100
```

### tts

TTS provider 配置（可插拔）。 **v0.2.4 默认 `edge`**（V2 #2.1 修复 VPS egress 后 flip）。

| Provider | 状态 | 何时可切默认 |
|---|---|---|
| `mock` | V1，返静默/音调 | 始终（V2 #2 改前默认） |
| `edge` | V2 #2 实现，V2 #2.1 修 egress 后 v0.2.4 默认 | **v0.2.4+ 默认** |
| `cloud` | V2 #1 骨架 | 未实现 |

```yaml
tts:
  provider: edge         # v0.2.4 默认
  voice: zh-CN-XiaoxiaoNeural   # 语音 ID
  rate: "+0%"                    # 语速
  volume: "+0%"                  # 音量
  options:
    chunk_ms: 60        # PCM chunk 大小（ms）
    boundary: SentenceBoundary  # 或 WordBoundary
    connect_timeout: 10  # edge-tts WS connect timeout (s)
    receive_timeout: 60  # edge-tts WS receive timeout (s)
```

**V2 #2 edge-tts 配置示例**（opt-in）：

```yaml
tts:
  provider: edge
  voice: zh-CN-XiaoxiaoNeural    # 默认；其他：en-US-JennyNeural, zh-CN-YunxiNeural
  rate: "+0%"                    # "-10%"~"+50%"
  volume: "+0%"
  pitch: "+0Hz"                  # 罕见调
  options:
    chunk_ms: 60                 # PCM chunk 大小（ms）
    boundary: SentenceBoundary   # 或 WordBoundary
    connect_timeout: 10          # WebSocket connect timeout (s)
    receive_timeout: 60          # WebSocket receive timeout (s)
```

**依赖**：V2 #2 加了 `edge-tts` + `pydub` pip 包。`bridge/Dockerfile`
已装 `ffmpeg`（V1 阶段为 mock TTS mp3 路径装的，V2 #2 复用，**不增加镜像层**）。
pydub 是 ffmpeg 的 Python 包装。

**部署前提**：VPS 容器需出口通 `speech.platform.bing.com:443`。
v0.2.3 部署时实测 docker bridge network 的 FORWARD 默认拒 egress，
需 host iptables 修复后才能切默认（实现本身已就绪，不受网络限制）。

### device

设备与会话管理。

```yaml
device:
  auth_token: ""         # 可选：设备的 Bearer token（留空 = 不校验）
  session_id_prefix: xiaozhi
```

> **V2 #4 起变化**：`device.echo_mode` 已删除（之前是
> 调试用“原样回”模式，跟 LLM pipeline 不互通，V1 后期就
> 没人用了）。 V2 #4 顺手删掉，配置文件中也不再有这个字段。

### mcp

MCP 端点配置（v0.2.11+）。

```yaml
mcp: {}
```

> **V2 #7 状态（v0.2.11）**：MCP 工具注**册**表**是**进**程**全**局**的**（`xiaozhi_bridge.mcp.tools._REGISTRY`），
> **不**需**要** config 配**置**。bridge 在**每**个** session 创**建**时** `_register_device_tools` 动**态**注**册** 3 个 esp32 端**工**具**（**get_device_status / set_volume / set_brightness**）。
> 会**话**关**闭**时** `_cleanup_session_tools` 动**态**解**绑**。**未**来** V2 #7.7 per-session MCP server 时**配**置**会**改**为**每**个** session 独**立**注**册**表**。
>
> **V2 #4 起变化**：`mcp.enabled` 和 `mcp.auto_initialize`
> 已删除。V1 后期决定不暴露 MCP（firmware 端的那路没起来，
> 跟 V2 #7 “reverse MCP” 一起重做）。

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

> **V2 #1 参考实现**：`sherpa_onnx` provider 是 v0.2.2 的首个真 ASR 实现。
> 看 `bridge/src/xiaozhi_bridge/asr/sherpa_onnx.py` 可以了解完整的
> “config 校验 + lazy load + 真转写循环”模板（~250 行，包括文档
> 化的 3 个 sherpa-onnx 坑点）。子类化 `ASRBase` 后只需重写
> `transcribe(audio, sample_rate, channels)`。

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
