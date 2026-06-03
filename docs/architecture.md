# 架构设计

> 本文档详细描述 xiaozhi-bridge 的系统架构、模块划分、数据流和设计决策。

## 1. 设计目标

1. **轻量**：单台 1-2GB 内存 VPS 可稳定运行
2. **可插拔**：ASR / TTS / LLM 都做成抽象接口，方便切换实现
3. **复用 openclaw 能力**：LLM 思考、工具调用、记忆都由 openclaw 提供
4. **完整复刻 xiaozhi-esp32-server 核心能力**：协议层、ASR/TTS、MCP IoT、智控台
5. **代码可读性优先**：个人学习项目，注释和文档详尽

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       VPS (Ubuntu 24.04)                          │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  openclaw gateway                                        │    │
│  │  - LLM 推理 (MiniMax M3)                                │    │
│  │  - 工具调用 (tool calling)                              │    │
│  │  - HTTP/WS API (:18789)                                 │    │
│  │  - MCP server (内置)                                    │    │
│  │  内存: ~200-300 MB                                      │    │
│  └──────────────────────────────────────────────────────────┘    │
│         ▲                                                          │
│         │ HTTP POST (LLM)  /  HTTP GET (工具查询)                │
│         │                                                          │
│  ┌──────┴───────────────────────────────────────────────────┐    │
│  │  bridge (Python asyncio)                                │    │
│  │  - WebSocket server (:8000)                             │    │
│  │  - xiaozhi 协议解析                                    │    │
│  │  - Opus 音频编解码                                      │    │
│  │  - ASR 抽象 (可插拔)                                    │    │
│  │  - TTS 抽象 (可插拔)                                    │    │
│  │  - LLM 客户端 (调 openclaw)                             │    │
│  │  - MCP JSON-RPC 2.0 端点                                │    │
│  │  - 设备会话管理                                         │    │
│  │  - 配置管理                                             │    │
│  │  内存: ~50-100 MB                                       │    │
│  └──────────────────────────────────────────────────────────┘    │
│         ▲                                                          │
│         │ HTTP                                                    │
│         │                                                          │
│  ┌──────┴───────────────────────────────────────────────────┐    │
│  │  web 智控台 (React SPA)                                 │    │
│  │  - 设备管理                                             │    │
│  │  - 实时对话                                             │    │
│  │  - IoT 设备管理                                         │    │
│  │  - 设置/日志                                            │    │
│  │  静态资源: ~5 MB                                        │    │
│  └──────────────────────────────────────────────────────────┘    │
│         ▲                                                          │
└─────────┼──────────────────────────────────────────────────────────┘
          │ HTTPS (Caddy 反代)
          │
   [用户浏览器]
```

## 3. 模块详解

### 3.1 bridge（Python 桥接服务）

#### 3.1.1 入口 (`main.py`)

- 读取配置（YAML/JSON）
- 初始化日志
- 启动 WebSocket server
- 注册信号处理（优雅关闭）

#### 3.1.2 协议层 (`protocol/`)

负责 xiaozhi WebSocket 协议：

- `messages.py`：所有消息类型定义（dataclass / pydantic）
  - 设备→服务器：`hello`, `listen` (Start/Stop/Detect), `abort`, `mcp` 请求
  - 服务器→设备：`stt`, `llm`, `tts` (start/sentence_start/stop), `mcp` 响应
- `audio.py`：Opus 音频解码
  - 16kHz / 24kHz
  - 60ms frame
  - 重采样（如需）
- `states.py`：设备会话状态机
  - `idle` → `listening` → `thinking` → `speaking` → `idle`

#### 3.1.3 ASR 抽象层 (`asr/`)

定义统一接口，可插拔多种实现：

```python
class ASRBase(Protocol):
    async def transcribe(self, audio: bytes, sample_rate: int) -> str:
        """音频字节流 → 文本"""
        ...
```

- `base.py`：接口定义 + 注册表
- `aliyun.py`：阿里云一句话识别
- `tencent.py`：腾讯云 ASR（占位）
- `xfyun.py`：讯飞 ASR（占位）
- `mock.py`：测试用 mock 实现

通过配置文件 `asr.provider: aliyun` 切换。

#### 3.1.4 TTS 抽象层 (`tts/`)

```python
class TTSBase(Protocol):
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """文本 → 音频字节流（边合成边推送）"""
        ...
```

- `base.py`：接口定义 + 注册表
- `edge.py`：Microsoft Edge TTS（免费）
- `sherpa_onnx.py`：本地 ONNX TTS（离线）
- `mock.py`：测试用 mock

#### 3.1.5 LLM 客户端 (`llm/`)

```python
class LLMClient(Protocol):
    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[LLMEvent]:
        """对话流式响应，yield LLMEvent（文本片段 / 工具调用 / 完成）"""
        ...
```

- `openclaw.py`：调用 openclaw gateway 的 `/v1/chat/completions`
- 支持 tool calling
- 支持 system prompt 注入（角色、性格、设备上下文）

#### 3.1.6 MCP 服务 (`mcp/`)

JSON-RPC 2.0 端点，处理 IoT 设备控制：

```python
methods = {
    "tools/list": ...,           # 列出可用工具
    "tools/call": ...,           # 调用工具
}
```

工具实现示例：
- `get_device_state` — 查询设备状态
- `set_volume` — 设置音量
- `iot_control` — 控制 IoT 设备（灯/风扇/空调等）

#### 3.1.7 配置 (`config.py`)

- 使用 Pydantic Settings
- 支持环境变量覆盖
- 支持热重载（开发模式）

### 3.2 openclaw 配置

#### 3.2.1 内置 MCP server

在 openclaw 配置中注册一个 MCP server，桥接服务通过它来"告诉"openclaw 调用工具。

或者更简单：openclaw 的工具由我们直接在 openclaw 端定义（通过 skills 或 tools 配置），桥接服务只负责转发 MCP JSON-RPC 消息。

#### 3.2.2 模型选择

- 主对话：**MiniMax M3**（1M context，思考）
- 流式响应：**MiniMax M3-highspeed**（200k，更快）
- 编码相关：默认 M3 即可

#### 3.2.3 系统 prompt 模板

在 `bridge/src/llm/prompts.py` 定义：
- 角色设定（智能助手）
- 设备上下文（设备名、当前时间、IoT 设备列表）
- 回复风格（短句、TTS 友好）
- 工具使用说明

### 3.3 web 智控台（React）

#### 3.3.1 技术栈

- **React 18** + **TypeScript**
- **Vite** 构建
- **shadcn/ui** 组件库
- **React Router** 路由
- **Zustand** 状态管理
- **TanStack Query** 服务端状态
- **Tailwind CSS** 样式
- **Lucide Icons** 图标

#### 3.3.2 页面

| 页面 | 路由 | 功能 |
|---|---|---|
| Dashboard | `/` | 设备状态总览、活跃会话、关键指标 |
| Devices | `/devices` | 设备列表、详情、配置 |
| Conversations | `/conversations` | 对话历史、搜索、回放 |
| Iot | `/iot` | IoT 设备管理、添加/删除/控制 |
| Settings | `/settings` | ASR/TTS/LLM 配置、个性化 |
| Logs | `/logs` | 实时日志流（WebSocket） |

#### 3.3.3 主题

- 现代极简风
- 暗色/亮色切换
- 移动端响应式

## 4. 数据流

### 4.1 一次完整对话

```
1. 用户说"小智，把灯打开"
   硬件采集音频（16kHz Opus，60ms 帧）
   硬件 → bridge: WebSocket binary frames (Opus)

2. bridge
   接收音频帧 → Opus 解码 → PCM 缓冲
   收到 "listen" Start 消息
   ASR.transcribe(PCM) → "把灯打开"
   bridge → 硬件: {"type": "stt", "text": "把灯打开"}

3. bridge → openclaw
   POST /v1/chat/completions
   messages = [
     {role: "system", content: "..."},
     {role: "user", content: "把灯打开"}
   ]
   tools = [iot_control_tool]

4. openclaw (M3)
   思考 → 决定调用 iot_control
   返回 tool_call: {"name": "iot_control", "args": {"device": "light", "action": "on"}}

5. bridge (MCP 端点)
   iot_control(light, on) → 实际操作硬件（或模拟）
   返回 tool_result

6. bridge → openclaw (第二次)
   传入 tool_result
   M3 生成最终回复："好的，灯已打开"

7. bridge → TTS
   "好的，灯已打开" → EdgeTTS 流式合成 → Opus 编码

8. bridge → 硬件
   {"type": "llm", "text": "好的，灯已打开", "emotion": "happy"}
   {"type": "tts", "state": "start"}
   WebSocket binary frames (Opus 音频)
   {"type": "tts", "state": "stop"}
   {"type": "tts", "state": "sentence_start", "text": "好的，灯已打开"}
```

### 4.2 IoT 控制

```
硬件 → bridge: {"type": "mcp", "payload": {"jsonrpc": "2.0", "method": "tools/call", "params": {...}}}
bridge: 解析 JSON-RPC → 调用对应 handler
bridge → 硬件: {"type": "mcp", "payload": {"jsonrpc": "2.0", "result": {...}}}
```

## 5. 部署架构

### 5.1 systemd 单元

- `xiaozhi-bridge.service`：桥接服务（Python）
- `xiaozhi-web.service`：智控台静态文件服务（Caddy 或 nginx）
- `openclaw-gateway.service`：openclaw gateway（已存在）

### 5.2 反向代理

Caddy 自动 HTTPS：
```
xiaozhi.example.com {
    reverse_proxy localhost:3000  # 智控台
    reverse_proxy /ws/* localhost:8000  # WebSocket
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
- Allen 之前确认 React + shadcn/ui

### 6.4 LLM 为什么用 openclaw 不直接调 MiniMax API？

- openclaw 提供工具调用、记忆、未来扩展能力
- 未来可一行代码加新 tool，不用改 bridge

## 7. 未来扩展（V2/V3）

- 多设备支持（设备 ID 路由）
- 知识库 / RAG（openclaw 端接 vector DB）
- 声纹识别
- MQTT 协议支持
- OTA 固件升级接口
- 多用户/多智能体

---

详细 API 规范见 [api.md](api.md)，协议细节见 [protocol.md](protocol.md)。
