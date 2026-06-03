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

> **方向说明**：MCP 协议原本是设备作为 MCP **server**、后端作为 MCP **client**。
> 但在我们的实现里，由于 LLM 思考在后端，**我们让后端（bridge + openclaw）作为 MCP client 端**，
> 设备作为 MCP server 端来**暴露**它的能力（如音量控制、IoT 设备列表等）。
>
> **注意**：原项目中 MCP 主要用于**设备能力发现**（设备有什么 tool 可用）。在我们这里，
> 大部分 IoT 工具放在 **openclaw 端**（通过 openclaw 的 tool calling），设备只需要执行底层动作。

### 5.1 方法列表

| 方法 | 方向 | 用途 |
|---|---|---|
| `initialize` | backend → device | 初始化 MCP 会话 |
| `tools/list` | backend → device | 列出设备能力 |
| `tools/call` | backend → device | 调用设备能力 |
| `notifications/...` | device → backend | 设备主动通知 |

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
- LLM 思考（交给 llm 模块）
- 实际 IoT 控制（交给 openclaw tool / mcp 模块）

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
| **房间灯/风扇/空调**（真实 IoT） | **openclaw tool**（调米家/Home Assistant） |
| **联网搜索/天气** | **openclaw tool**（LLM 思考时调用） |
| **闹钟/提醒** | **openclaw tool** |

**架构原则**：
- **设备层 MCP** = 设备自身能力（音量、屏幕、板载 LED）
- **openclaw tool** = 外部世界能力（IoT 设备、搜索、知识）
- LLM 通过 openclaw 的 tool calling 统一调用
