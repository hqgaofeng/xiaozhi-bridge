# 架构设计

> 本文档描述 xiaozhi-bridge 的系统架构、模块划分、数据流和设计决策。
>
> **V1 现状（2026-06-03）**：bridge 调 openclaw agent 端点（OpenAI 协议）、服务跑在 VPS 上，公网地址 `https://jarvis.beallen.top`。
>
> 详细版本变更：[changelog.md](changelog.md)。V1 发布说明：[v1-release-notes.md](v1-release-notes.md)。

## 1. 设计目标

1. **轻量**：单台 1-2GB 内存 VPS 可稳定运行
2. **可插拔**：ASR / TTS / LLM 都做成抽象接口，方便切换实现
3. **复用 openclaw 能力**：LLM 思考、工具调用、记忆都由 openclaw 提供
4. **完整复刻 xiaozhi-esp32-server 核心能力**：协议层、ASR/TTS、MCP IoT、智控台
5. **代码可读性优先**：个人学习项目，注释和文档详尽

## 2. 总体架构（V1）

```
                ┌─────────────────────────────────────┐
                │  公网（HTTPS）                       │
                │  nginx (host)  :80 → 301            │
                │  nginx (host)  :443 (Let's Encrypt) │
                │   ├─ /         → web 智控台         │
                │   ├─ /xiaozhi/ → bridge WebSocket   │
                │   └─ /api/     → bridge HTTP (V2)   │
                │  jarvis.beallen.top                  │
                └──────────────┬───────────────────────┘
                               │ WSS
                               ▼
   ┌──────────────────────────────────────────────────────────┐
   │  bridge 容器  (Python 3.12, asyncio, ~50-100 MB)        │
   │  ws://0.0.0.0:8000/xiaozhi/v1/  (loopback 对外)         │
   │  ┌──────────────┐  ┌────────────┐  ┌──────────────┐    │
   │  │ protocol/    │  │ asr/       │  │ tts/         │    │
   │  │ - messages   │  │ - base     │  │ - base       │    │
   │  │ - states     │  │ - mock     │  │ - mock       │    │
   │  │ - audio      │  │            │  │   (opuslib)  │    │
   │  └──────────────┘  └────────────┘  └──────────────┘    │
   │  ┌──────────────┐  ┌────────────┐                       │
   │  │ llm/         │  │ mcp/       │                       │
   │  │ - openclaw   │  │ - server   │                       │
   │  │   (OpenAI 协)│  │ - tools    │                       │
   │  │ - prompts    │  │  device    │                       │
   │  └──────────────┘  │  tools     │                       │
   │                     │  (3 个)    │                       │
   │                     └────────────┘                       │
   │  structlog JSON 日志                                     │
   └──────────┬───────────────────────────────────────────────┘
              │ HTTP POST /v1/chat/completions
              │   (Bearer gateway.auth.token)
              │   model: "openclaw"
              │   user: "xiaozhi-bridge" (会话隔离)
              │   stream: true
              ▼
   ┌──────────────────────────────────────────────────────────┐
   │  openclaw gateway  (host 上跑 systemd, ~200-300 MB)     │
   │  bind: "lan" → 0.0.0.0:18789                             │
   │                                                          │
   │  接收 /v1/chat/completions                                │
   │  调 default agent（agents.defaults 配置）                │
   │  agent 自己管：                                           │
   │    - system prompt（不在 bridge 里）                     │
   │    - 工具调用（tool calling, bridge 看不到）             │
   │    - 会话记忆（基于 user 派生的 sessionKey）             │
   │    - 后端 LLM 路由（默认 MiniMax-M3，可 x-openclaw-model 覆盖）│
   │  流式 SSE 返回文本                                        │
   └──────────────────────────────────────────────────────────┘
```

**V1 部署组件**：

| 组件 | 跑在哪 | 端口（对外）| 备注 |
|---|---|---|---|
| xiaozhi-bridge (容器) | docker | 127.0.0.1:8000 | WebSocket，loopback |
| xiaozhi-web (容器) | docker | 127.0.0.1:5180 | React 静态，loopback |
| openclaw (host) | systemd | 0.0.0.0:18789 | bind=lan |
| nginx (host) | systemd | 80 / 443 | TLS + 反代 |
| Let's Encrypt | host | - | certbot 签发 |

> **V1 不再有 caddy service、openclaw service**——全在 host 跑，避免容器内 80/443 跟宿主 nginx 冲突。

## 3. 模块详解

### 3.1 bridge（Python 桥接服务）

#### 3.1.1 入口 (`main.py`)

- 读取配置（YAML + 环境变量覆盖）
- 初始化 structlog（JSON 输出）
- 启动 WebSocket server
- 注册信号处理（优雅关闭）

#### 3.1.2 协议层 (`protocol/`)

负责 xiaozhi WebSocket 协议：

- `messages.py`：所有消息类型定义（dataclass / pydantic）
  - 设备→服务器：`hello`, `listen` (start/stop, mode: auto/manual), `abort`, `mcp` 请求
  - 服务器→设备：`stt`, `llm`, `tts` (start/sentence_start/sentence_end/stop), `mcp` 响应
- `audio.py`：Opus 音频编解码
  - 16kHz / 24kHz
  - 60ms frame
  - opuslib（V1 真用）
- `states.py`：设备会话状态机
  - `idle` → `listening` → `thinking` → `speaking` → `idle`

#### 3.1.3 ASR 抽象层 (`asr/`)

```python
class ASRBase(Protocol):
    async def transcribe(self, audio: bytes, sample_rate: int) -> str: ...
```

- `base.py`：接口定义 + 注册表
- `mock.py`：测试用 mock（V1 真用）
- 真 ASR（aliyun / tencent / xfyun / funasr）—— **V2 TODO**

#### 3.1.4 TTS 抽象层 (`tts/`)

```python
class TTSBase(Protocol):
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]: ...
```

- `base.py`：接口定义 + 注册表
- `mock.py`：用 opuslib 把文本编码成 Opus 60ms 帧（V1 真用）
- 真 TTS（edge-tts / 火山引擎 / GPT-SoVITS）—— **V2 TODO**

#### 3.1.5 LLM 客户端 (`llm/openclaw.py`)

bridge 调 openclaw gateway 的 `/v1/chat/completions`（OpenAI 兼容协议）。

**关键设计**：

- **Agent target 模式**：`model: "openclaw"`（不是 `minimax/MiniMax-M3` 之类的后端 LLM id）
  - openclaw 端 `agents.defaults` 配置决定实际后端 LLM
  - bridge 不关心后端是什么 LLM
- **可选后端覆盖**：`x-openclaw-model: minimax/MiniMax-M3-highspeed` header 可强制选 LLM
  - 配置项：`openclaw.backend_model`（V1 默认空 = 走 openclaw agent 默认）
- **Session 隔离**：传 `user: "xiaozhi-bridge"`，openclaw 派生 `openai-user:xiaozhi-bridge` session key
  - **完全独立**于主会话 `agent:default-main:openai-user:8682984776`
  - 你在主会话（这个对话）跟 device 会话的历史**互不干扰**
- **鉴权**：`Authorization: Bearer <gateway.auth.token>`
  - 从 `~/.openclaw/openclaw.json` 的 `gateway.auth.token` 拿
- **不传 `tools[]`**：openclaw 自带 tool registry（web_search / IoT / 知识），外部 `tools[]` 会被拒
- **不传 system prompt**：由 openclaw agent 自己的 system prompt 控制（在 openclaw 端配）
- **流式响应**：SSE 解析、拼成完整 LLM 响应文本（`prompts.py` 保留语音助手人设参考模板，供 openclaw agent 配置用）

**错误处理**：
- 401 / 403 → 返 fallback 短句 + 警告
- 超时 / 网络错 → 返 fallback 短句 + 结构化错误日志
- 永远不杀进程，session 状态保持可恢复

#### 3.1.6 MCP 服务 (`mcp/`)—— bridge 内置工具

**V1 方向**：bridge **既是 MCP server（向设备暴露设备能力查询 / 音量 / LED 控制）**，**也是 MCP client（向设备要 `tools/list`）**。

JSON-RPC 2.0 端点：
```python
methods = {
    "initialize": ...,    # 设备→bridge 初始化
    "tools/list": ...,    # 双向
    "tools/call": ...,    # 设备→bridge 调用工具
}
```

**bridge 内置工具**（`mcp/tools.py`，190 行）—— V1 实际实现的 3 个：

- `self.get_device_status` — 返回设备状态（音量、亮度、Wi-Fi、电量 mock）
- `self.audio_speaker.set_volume` — 调音量（V1 只 log，不发到设备）
- `self.led.set_rgb` — 调板载 LED（V1 只 log）

**这些工具是 V1 占位**（未来 V2 会加 `turn_on/off_light`、`get_time`、`get_weather`、接真 IoT / HA / 米家等）。**目前**工具是 bridge **自己实现**的，**不**走 openclaw tool calling。

**跟 openclaw tool 的关系**：
- openclaw agent **自己有** 一套 tool registry（web_search / IoT 平台接入 / 知识库等）
- bridge **不解析 tool_call**，openclaw agent 内部完成
- M3 追问"哪里的灯？什么品牌？"——那是 openclaw 自带的 tool，bridge 完全看不到
- bridge 只消费 openclaw 流式返回的**最终文本**

#### 3.1.7 配置 (`config.py`)

- Pydantic Settings
- YAML 文件 + `XIAOZHI_<SECTION>__<FIELD>` 环境变量覆盖
- 双下划线 `__` 表示嵌套
- `config/config.yaml` 在 `.gitignore` 里——不进 git
- 模板：`config/config.example.yaml`

### 3.2 openclaw 配置（V1 必须改的两处）

> 这两处在 `~/.openclaw/openclaw.json` 里改，**不在**本项目仓库里。

#### 3.2.1 开启 chatCompletions endpoint

openclaw 默认**不**暴露 `/v1/chat/completions`，bridge 需要它：

```json
{
  "gateway": {
    "http": { "endpoints": { "chatCompletions": { "enabled": true } } }
  }
}
```

#### 3.2.2 bind 改非 loopback

openclaw 默认只听 127.0.0.1，bridge 容器从 `host.docker.internal` 走不通。改成：

```json
{
  "gateway": {
    "bind": "lan"        // 0.0.0.0
  }
}
```

VPS 内网有不可信用户时改 `custom` 绑 docker bridge gateway IP：

```json
{
  "gateway": {
    "bind": "custom",
    "customBindHost": "172.17.0.1"
  }
}
```

```bash
openclaw config validate
systemctl --user restart openclaw-gateway
ss -tlnp | grep 18789   # 应看到 0.0.0.0:18789
```

### 3.3 web 智控台（React）

#### 3.3.1 技术栈

- **React 19** + **TypeScript 5.6**
- **Vite 7** 构建
- **Tailwind CSS 3** 样式
- **React Router 7** 路由
- **Zustand** 状态管理
- **shadcn/ui 风格** 组件（手写 Tailwind）
- **Lucide Icons** 图标

#### 3.3.2 页面

| 页面 | 路由 | 功能 | 数据源 |
|---|---|---|---|
| Dashboard | `/` | 设备状态总览、活跃会话、关键指标 | **mock** |
| Devices | `/devices` | 设备列表、详情、配置 | **mock** |
| Conversations | `/conversations` | 对话历史、搜索、回放 | **mock** |
| IoT | `/iot` | IoT 设备管理、添加/删除/控制 | **mock** |
| Settings | `/settings` | ASR/TTS/LLM 配置、个性化 | **mock** |
| Logs | `/logs` | 实时日志流（WebSocket） | **mock** |

> V1 智控台**全是 mock 数据**——V2 TODO：接 bridge `/api/` HTTP API（V1 还没实现）

#### 3.3.3 部署

- `web/` 容器内置 Caddy 服务静态文件
- 监听 `127.0.0.1:5180:80`（loopback）
- 宿主 nginx `location /` 反代到 5180

## 4. 数据流（V1 实际路径）

### 4.1 一次完整对话

```
1. 用户说"现在几点"
   硬件采集音频（16kHz Opus，60ms 帧）
   硬件 → bridge: WebSocket binary frames (Opus)

2. bridge
   接收音频帧 → Opus 解码 → PCM 缓冲
   收到 "listen" start 消息
   ASR.mock.transcribe(PCM) → "现在几点"
   bridge → 硬件: {"type": "stt", "text": "现在几点"}

3. bridge → openclaw
   POST http://host.docker.internal:18789/v1/chat/completions
   Headers:
     Authorization: Bearer <gateway.auth.token>
     Content-Type: application/json
   Body:
     {
       "model": "openclaw",        // agent target
       "stream": true,
       "user": "xiaozhi-bridge",   // 派生独立 sessionKey
       "messages": [
         {"role": "user", "content": "现在几点"}
       ]
       // 不传 tools[] / system —— openclaw agent 自己有
     }

4. openclaw agent
   接收请求 → 派生 sessionKey = openai-user:xiaozhi-bridge
   读 openclaw agent 配置（agents.defaults）→ 选默认 LLM
   调 LLM（MiniMax-M3）→ 思考
   调 openclaw 内置 tool: get_current_time() → 拿到时间
   拼最终文本："现在是 2026-06-03 05:19 UTC（布法罗当地时间凌晨 1:19 AM）"
   SSE 流式返 bridge

5. bridge
   SSE 解析 → 拼成完整文本
   切句（按句号/问号）
   TTS.mock.synthesize_stream(text) → opuslib 编码成 60ms Opus 帧

6. bridge → 硬件
   {"type": "llm", "emotion": "neutral", "text": "🤔"}
   {"type": "tts", "state": "start"}
   {"type": "tts", "state": "sentence_start", "text": "现在是 2026-06-03 05:19 UTC（布法罗当地时间凌晨 1:19 AM）"}
   WebSocket binary frames (Opus 音频)
   {"type": "tts", "state": "sentence_end"}
   {"type": "tts", "state": "stop"}
   → 状态回到 idle
```

### 4.2 IoT 控制（V1 demo）

```
硬件 → bridge: {"type": "mcp", "payload": {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "self.audio_speaker.set_volume", "arguments": {"volume": 50}}}}
bridge: 解析 JSON-RPC → 调 mcp/tools.py 里 set_volume(50)
         (V1 只 log，不下到设备)
bridge → 硬件: {"type": "mcp", "payload": {"jsonrpc": "2.0", "result": {"ok": true}}}
bridge → 硬件: {"type": "mcp", "payload": {"jsonrpc": "2.0", "result": {"ok": true}}}
```

> **真 IoT**（米家 / Home Assistant / Hue）走 openclaw 端 tool registry，bridge 看不到。
> V1 demo 灯是 mock，**不**接真硬件。

## 5. 部署架构（V1）

### 5.1 systemd 单元

- `openclaw-gateway.service`：openclaw gateway（已有）
- `nginx.service`：宿主 nginx（已有，反代 80/443）
- `certbot.timer`：Let's Encrypt 自动续期（已有）
- ~~`xiaozhi-bridge.service`~~：V1 改用 docker compose 管理（不写 systemd）
- ~~`xiaozhi-web.service`~~：同上

### 5.2 反向代理

**V1 不用 caddy**（caddy service 删了）。改用宿主上已有的 nginx：

```nginx
# /etc/nginx/conf.d/jarvis.beallen.top.conf
server {
    listen 80;
    server_name jarvis.beallen.top;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name jarvis.beallen.top;
    ssl_certificate     /etc/letsencrypt/live/jarvis.beallen.top/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jarvis.beallen.top/privkey.pem;

    location /         { proxy_pass http://127.0.0.1:5180; }   # web
    location /api/     { proxy_pass http://127.0.0.1:8000/api/; } # bridge HTTP (V2)
    location /xiaozhi/ {                                            # bridge WS
        proxy_pass http://127.0.0.1:8000/xiaozhi/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
    location = /health { proxy_pass http://127.0.0.1:8000/health; }
}
```

## 6. 关键技术决策

### 6.1 为什么用 Python 而不是 Node.js 做桥接？

- ASR/TTS 库生态 Python 更丰富
- asyncio + websockets 性能足够
- 个人维护成本低（Allen 偏好）

### 6.2 为什么不用 xiaozhi-esp32-server 的代码直接改？

- 原项目太重，资源消耗大
- 跟 FunASR/Mysql/Vue 强耦合
- 我们的目标是**极简可插拔**

### 6.3 为什么智控台用 React 而不是 Vue？

- shadcn/ui 是 React 生态的（Vue 也有但没这么成熟）
- Allen 之前确认 React + shadcn/ui 风格

### 6.4 LLM 为什么用 openclaw 不直接调 MiniMax API？

- openclaw 提供工具调用、记忆、未来扩展能力
- 未来可一行代码加新 tool，不用改 bridge
- **V1 验证**：openclaw agent 自带的 tool（"灯品牌 / 房间名"追问）就是 openclaw 端处理，bridge 完全不感知

### 6.5 为什么 agent target `model: "openclaw"` 而不是 `model: "minimax/MiniMax-M3"`？

- `openclaw` = agent 端点（让 openclaw 用 agents.defaults 配置的 agent 来处理）
- `minimax/MiniMax-M3` = 后端 LLM 直连（绕开 agent，不走 tool calling、不走 system prompt、不走 sessionKey 派生）
- V1 选 agent target 模式，因为：
  - 想用 openclaw 自带 tool（get_current_time / IoT / 搜索）
  - 想用 openclaw 端配置的 system prompt
  - 想用 sessionKey 派生机制做会话隔离

## 7. V2 / V3 TODO（12 个候选）

按推荐顺序：

1. **真 ASR**（funasr / sherpa-onnx / 阿里云）
2. **真 TTS**（edge-tts / 火山引擎 / GPT-SoVITS）
3. **FastAPI HTTP API**（`/api/devices`、`/api/conversations`、`/api/iot`、`/api/config`、`/api/logs/stream`）
4. **SQLite 对话持久化**
5. **智控台接真数据**（调 `/api/`）
6. **多设备管理**（设备 ID 路由 + 设备表）
7. **反向 MCP**（openclaw 主动调 ESP32 上的传感器/动作）
8. **OTA 固件更新**
9. **MQTT 协议支持**
10. **声纹识别**
11. **RAG / 知识库**
12. **负载均衡 / Prometheus / 告警 / 备份**

详细：[changelog.md](changelog.md)、[v1-release-notes.md](v1-release-notes.md)。

---

详细 API 规范见 [api.md](api.md)，协议细节见 [protocol.md](protocol.md)，配置说明见 [config.md](config.md)。
