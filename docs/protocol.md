# xiaozhi WebSocket 协议详解

> 本文档是 xiaozhi-bridge 实现协议的参考规范。
>
> 原始协议文档：[78/xiaozhi-esp32/docs/websocket_zh.md](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket_zh.md)
>
> 原始 MCP 文档：[78/xiaozhi-esp32/docs/mcp-protocol.md](https://github.com/78/xiaozhi-esp32/blob/main/docs/mcp-protocol.md)

## 1. 总览

xiaozhi 设备与后端通过 **WebSocket** 通信，使用：
- **JSON 文本帧** — 控制消息、状态、聊天内容
- **Opus 二进制帧** — 音频数据（双向）

请求头：
- `Authorization: Bearer <token>` — 鉴权
- `Protocol-Version: 1` — 协议版本
- `Device-Id: <MAC>` — 设备 MAC
- `Client-Id: <UUID>` — 客户端 UUID

## 2. 握手流程

### 2.1 设备→服务器 `hello`

```json
{
  "type": "hello",
  "version": 1,
  "features": {
    "mcp": true
  },
  "transport": "websocket",
  "audio_params": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

### 2.2 服务器→设备 `hello`（应答）

```json
{
  "type": "hello",
  "transport": "websocket",
  "session_id": "xxx",
  "audio_params": {
    "format": "opus",
    "sample_rate": 24000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

**我们实现**：握手成功后生成 `session_id`（UUID），双方以此关联会话。

## 3. 设备→服务器消息

### 3.1 `listen` — 监听状态

```json
{
  "session_id": "xxx",
  "type": "listen",
  "state": "start",        // start | stop | detect
  "mode": "auto"           // auto | manual | realtime
}
```

- `start` — 开始录音
- `stop` — 停止录音
- `detect` — 唤醒词检测（可携带 text 字段）

### 3.2 `abort` — 终止

```json
{
  "session_id": "xxx",
  "type": "abort",
  "reason": "wake_word_detected"
}
```

### 3.3 `mcp` — MCP JSON-RPC 2.0

```json
{
  "session_id": "xxx",
  "type": "mcp",
  "payload": {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
      "content": [
        { "type": "text", "text": "true" }
      ],
      "isError": false
    }
  }
}
```

## 4. 服务器→设备消息

### 4.1 `stt` — 语音识别结果

```json
{
  "session_id": "xxx",
  "type": "stt",
  "text": "用户说的话"
}
```

### 4.2 `llm` — 大模型回复（含表情）

```json
{
  "session_id": "xxx",
  "type": "llm",
  "emotion": "happy",      // happy | sad | angry | neutral | ...
  "text": "😀"             // 表情 emoji
}
```

### 4.3 `tts` — 语音合成状态

```json
// 开始
{ "session_id": "xxx", "type": "tts", "state": "start" }
// 一句话开始（带文本）
{ "session_id": "xxx", "type": "tts", "state": "sentence_start", "text": "..." }
// 停止
{ "session_id": "xxx", "type": "tts", "state": "stop" }
```

**TTS 音频**：在 `tts.start` 和 `tts.stop` 之间通过二进制 Opus 帧传输。

### 4.4 `mcp` — MCP 请求

```json
{
  "session_id": "xxx",
  "type": "mcp",
  "payload": {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "self.light.set_rgb",
      "arguments": { "r": 255, "g": 0, "b": 0 }
    },
    "id": 1
  }
}
```

### 4.5 `system` — 系统控制

```json
{ "session_id": "xxx", "type": "system", "command": "reboot" }
```

支持命令：`reboot`（V2）

## 5. MCP 协议（JSON-RPC 2.0）

> **V1 + V2 #7 方向**：MCP 协议原本是设备作为 MCP **server**、后端作为 MCP **client**。
> 在 xiaozhi-bridge 里，bridge 既是 **server**（向设备提供 MCP 端点、让设备能调 `get_time`/`get_weather`/demo 灯控制），
> 也是 **client**（在握手后向设备请求 `tools/list` 以了解设备能力）。
>
> **V2 #7 改变**：bridge **现**在**会**主**动**调**用**设备端**工**具**（**set_volume / set_brightness / get_device_status**）**。
>  协议**本**身**没**变**（**依**然**是** JSON-RPC 2.0 over xiaozhi WS `type=mcp` 消息**）**；
>  变**化**的**是** bridge 把 esp32 端**工**具**注**册**到** MCP registry，**当** LLM 决**定**调**用**某**个**工**具**时，bridge 通过 `tools/call` **发** JSON-RPC 给** esp32 执**行**并 await 响**应**。
>
> **跟 openclaw 的关系**（V2 #7）：
> - bridge **现**在**会**传** `tools[]` 给 openclaw（包**括** esp32 端** DeviceToolHandler + bridge 本**地** FunctionTool）
> - openclaw **把** `tool_calls` SSE delta 原**样**回**传**给 bridge
> - bridge 拿**到** `tool_call` 事**件**后调 MCP registry：对 esp32 端** DeviceToolHandler 发** JSON-RPC `tools/call`；对 bridge 本**地** FunctionTool 直**接**调**用** Python 函**数**
> - 响**应**以** `role=tool` message 喂**回** openclaw，LLM 继**续**产**生**最**终**文**本**
> - V2 #7 **不**改** openclaw 内**部**工**具**（**web_search / IoT 平台**）**。**只**是**让** openclaw 看**到** esp32 端**工**具**并**让** bridge 转**发**调**用**
>
> **原来的设计**（仅历史参考）：原 xiaozhi 项目里，后端发 MCP 给设备查“设备有什么 tool”。V1 保留了设备能力发现（声音控制、板载 LED 等），
> 但**普通 IoT 工具** 是在 bridge 里实现，不走 openclaw 的 tool calling。**V2 #7** 把"bridge 调设备 tool"**从** V1 的 "log only" 升**级**为** "**真**实** JSON-RPC 透**过** esp32 mcp_server"**。

### 5.1 方法列表

| 方法 | 方向 | 用途 | 实现阶**段** |
|---|---|---|---|
| `initialize` | backend → device | 初始化 MCP 会话 | V1 |
| `tools/list` | backend → device | 列出设备能力 | V1 |
| `tools/call` | backend → device | **bridge 主动调** esp32 端 tool | **V2 #7（重**点**）** |
| `tools/call` | device → backend | 设备调 bridge 端 tool（V1 占位 log only） | V1 |
| `notifications/...` | device → backend | 设备主动通知 | V1 |

### 5.2 `initialize`

请求：
```json
{
  "jsonrpc": "2.0",
  "method": "initialize",
  "params": {
    "capabilities": {
      "vision": { "url": "http://...", "token": "..." }
    }
  },
  "id": 1
}
```

响应：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": { "tools": {} },
    "serverInfo": {
      "name": "xiaozhi-esp32",
      "version": "1.0.0"
    }
  }
}
```

### 5.3 `tools/list`

请求：
```json
{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "params": { "cursor": "", "withUserTools": false },
  "id": 2
}
```

响应：
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "self.get_device_status",
        "description": "...",
        "inputSchema": { /* JSON Schema */ }
      }
    ],
    "nextCursor": ""
  }
}
```

### 5.4 `tools/call`

请求：
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "self.audio_speaker.set_volume",
    "arguments": { "volume": 50 }
  },
  "id": 3
}
```

成功响应：
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{ "type": "text", "text": "true" }],
    "isError": false
  }
}
```

错误响应：
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32601,
    "message": "Unknown tool: self.non_existent_tool"
  }
}
```

## 6. 音频帧（Opus 二进制）

- **协议版本 1**：直接发送 Opus 数据
- **协议版本 2**：`BinaryProtocol2` 结构（带时间戳，用于服务器端 AEC）
- **协议版本 3**：`BinaryProtocol3` 结构（简化版）

**V1 实现**：只支持版本 1（最简单，覆盖 90% 设备）。

## 7. 状态机

```
[Idle] ──listen start──> [Listening] ──tts start──> [Speaking]
   ▲                         │                          │
   │                         └─abort────────────────────┤
   │                                                    │
   └─────────────────tts stop───────────────────────────┘
```

## 8. 实现要点

### 8.1 协议层职责
- JSON 消息解析/序列化
- Opus 音频解码（接收设备音频）
- Opus 音频编码（发送 TTS 音频）
- 会话状态管理
- 协议版本协商

### 8.2 不在协议层做的事
- ASR（交给 asr 模块）
- TTS（交给 tts 模块）
- LLM 思考（交给 openclaw agent。bridge 走 `/v1/chat/completions` 流式拉文本，不解析 tool_call）
- 设备内置 MCP 工具调用（交给 bridge mcp 模块：`bridge/src/xiaozhi_bridge/mcp/`）
- 外部 IoT / 联网 / 知识（交给 openclaw agent 自带 tool，bridge 看不到细节）

## 9. 错误处理

- JSON 缺少 `type` 字段 → 忽略 + 日志
- 二进制帧协议版本不匹配 → 协议降级到 v1
- MCP 错误码遵循 JSON-RPC 2.0：
  - `-32700` Parse error
  - `-32600` Invalid Request
  - `-32601` Method not found
  - `-32602` Invalid params
  - `-32603` Internal error

## 10. 兼容性

- 我们实现**协议 v1 + 部分 v2**（带时间戳，便于 AEC）
- 支持 `mcp` 特性
- 不支持旧版 `type: "iot"`（已废弃）

## 11. 完整对话示例

```jsonc
// 1. 设备连接
→ {"type": "hello", "version": 1, "features": {"mcp": true}, "transport": "websocket", "audio_params": {...}}
← {"type": "hello", "transport": "websocket", "session_id": "abc123", "audio_params": {...}}

// 2. 设备唤醒
→ {"session_id": "abc123", "type": "listen", "state": "start", "mode": "auto"}
→ [Opus binary frames... 用户说话]

// 3. ASR 结果
← {"session_id": "abc123", "type": "stt", "text": "今天天气怎么样"}

// 4. LLM 思考
← {"session_id": "abc123", "type": "llm", "emotion": "neutral", "text": "🤔"}

// 5. TTS 开始
← {"session_id": "abc123", "type": "tts", "state": "start"}
← {"session_id": "abc123", "type": "tts", "state": "sentence_start", "text": "今天北京晴天，25度"}
→ [Opus binary frames... TTS 音频]
← {"session_id": "abc123", "type": "tts", "state": "stop"}

// 6. 设备继续监听（自动模式）
→ {"session_id": "abc123", "type": "listen", "state": "stop"}
→ {"session_id": "abc123", "type": "listen", "state": "start", "mode": "auto"}
```

## 12. 工具实现映射

| 设备能力 | 在我们的实现里 |
|---|---|
| `self.get_device_status` | bridge 维护设备状态 |
| `self.audio_speaker.set_volume` | bridge → device MCP |
| `self.light.set_rgb`（板载 LED） | bridge → device MCP |
| `self.screen.set_brightness`（V2） | bridge → device MCP |
| **get_time / get_weather / turn_on/off_light**（内测工具） | **bridge MCP**（`bridge/src/xiaozhi_bridge/mcp/tools.py`） |
| **联网搜索 / 外部 IoT / 知识** | **openclaw agent 自带 tool**（bridge 看不到细节） |

**V1 架构原则**：
- **设备层 MCP** = 设备自身能力（音量、屏幕、板载 LED）
- **bridge MCP** = 内置实用工具（`get_time`、`get_weather`、灯/风扇 demo）。bridge 走 `tools/list` 把自己注册到设备的能力池里，设备发出的 `tools/call` 走 bridge 处理。
- **openclaw agent tool** = openclaw 内部 agent 框架的 tool（openclaw 走自己的 tool calling、不经过 bridge）。bridge 只**消费** openclaw 返回的最终文本。
- LLM 不走 bridge 这一侧 tool_call 路径。**bridge 不解析 tool_call**，openclaw agent 内部完成 tool 调用。
