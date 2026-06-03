# HTTP API 文档

> xiaozhi-bridge 提供的 HTTP API（V2 #3 已实现，v0.2.0）
>
> V1 只暴露 WebSocket（xiaozhi 协议）；V2 #3 加入了 FastAPI HTTP API。
>
> 完整实现见 `bridge/src/xiaozhi_bridge/server.py`（V1） + `bridge/src/xiaozhi_bridge/api/`（V2 #3）。
>
> API 进程**独立于** bridge WS 进程，端口 8001。nginx `/api/` → 8001。

## 基础信息

- **Base URL**：`http://127.0.0.1:8001/api`（开发）或 `https://jarvis.beallen.top/api`（生产）
- **进程**：bridge-api（独立于 bridge WS）
- **认证**：V1 无；V2 计划加 JWT
- **数据格式**：JSON
- **CORS**：默认放行 `http://localhost:3000`、`http://localhost:5180`、`https://jarvis.beallen.top`

## 端点（V2 #3 已实现，v0.2.0）

### Health

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| `GET` | `/api/health` | liveness probe | ✅ 200 |

### Devices 设备

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| `GET` | `/api/devices` | 列出所有设备（联接活跃 session） | ✅ |
| `GET` | `/api/devices/{id}` | 设备详情 | ✅ 200 / 404 |
| `POST` | `/api/devices/{id}/reboot` | 重启设备 | ⏳ 501（V2 接入 WS abort） |

#### `GET /api/devices`

响应：
```json
[
  {
    "id": "esp32-001",
    "name": "esp32-001",
    "mac": "esp32-001",
    "state": "idle",
    "lastSeen": 1780480757.29,
    "sessionId": "xiaozhi-6b5bcb3b9d93"
  }
]
```

### Conversations 对话

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| `GET` | `/api/conversations` | 列出对话（?deviceId, ?limit=1..500） | ✅ |
| `GET` | `/api/conversations/{id}` | 对话详情（id 整数） | ✅ 200 / 400 / 404 |
| `GET` | `/api/conversations/{id}/audio/{turn}` | 音频流 | ❌ V2 #4 TODO |

#### `GET /api/conversations`

响应（V2 #3 schema，每个 conversation 包含 turns 数组）:
```json
[
  {
    "id": "2",
    "deviceId": "",
    "sessionId": "xiaozhi-6b5bcb3b9d93",
    "startedAt": 1780480757.29,
    "endedAt": 1780480757.29,
    "turns": [
      {"role": "user",      "text": "你好小智",   "timestamp": 1780480757.29},
      {"role": "assistant", "text": "你好！我是贾维斯，不是小智",  "timestamp": 1780480757.29}
    ],
    "llmStatus": "ok"
  }
]
```

### IoT 设备

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| `GET` | `/api/iot` | 列出 IoT 设备 | ✅ 2 个 demo seed |
| `POST` | `/api/iot/{id}/control` | 控制设备 | ✅ V1 改 db 状态 |
| `POST` | `/api/iot` | 添加设备 | ❌ V2 #6 TODO |
| `DELETE` | `/api/iot/{id}` | 删除设备 | ❌ V2 #6 TODO |

#### `POST /api/iot/{id}/control`

请求：
```json
{
  "action": "on",
  "value": 100
}
```

响应（设备当前状态）:
```json
{
  "id": "light-1",
  "name": "客厅灯",
  "type": "light",
  "room": "客厅",
  "online": true,
  "state": { "action": "on", "value": 100, "ts": 1780480359.18 }
}
```

### Settings 设置

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| `GET` | `/api/config` | 获取当前配置 | ✅ V1 返 `{}` |
| `PATCH` | `/api/config` | 更新配置 | ✅ V1 存 db 不应用 |

### Logs 日志

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| `GET` | `/api/logs/stream` | SSE 实时日志流 | ⏳ V1 heartbeat 占位（每 2s） |

## 架构说明

### bridge-api 跨进程设计

bridge-api 跟 bridge WS **不共享内存**。两者都是独立 uvicorn 进程，
通过 `/app/data/bridge.db`（docker 里的 named volume）交换状态：

- bridge 进程 **写**：每个 session 状态转换 + 每个完成的 turn
- bridge-api 进程 **读**：HTTP GET 请求查 db

共享库：`bridge/src/xiaozhi_bridge/api/db.py`（`BridgeDB` 类 + aiosqlite
+ WAL 模式 + busy_timeout=5000）。bridge 进程和 API 进程**各自 new
一个 BridgeDB 实例**，但连同一个 db 文件。

### 端到端验证（2026-06-03）

- 公网 `wss://jarvis.beallen.top/xiaozhi/v1/` 跑完两个完整 turn
  （STT"讲个笑话"→ M3 返程序员笑话 + STT"你好小智"→ M3 返
  "我是贾维斯"），`https://jarvis.beallen.top/api/conversations`
  能读到这两条。
- `https://jarvis.beallen.top/api/iot` 默认 seed 了 light-1 +
  switch-1 两个 demo 设备（让智控台预启时就有东西可看）。
- `https://jarvis.beallen.top/api/devices/abc/reboot` 返 501 + 提示
  "V2 will add WebSocket-triggered reboot"。

## V1 状态

V1 **没有 HTTP API**，仅 WebSocket。智控台（web/）V1 全部是 mock 数据。
V2 #3 解锁了 “接真数据” 路径；V2 #5 任务是把 web 里的 mock fetch 换成
对 /api/* 的真 fetch。
