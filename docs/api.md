# HTTP API 文档

> xiaozhi-bridge 提供的 HTTP API（V2）
>
> V1 只暴露 WebSocket（xiaozhi 协议），HTTP API 是 V2 阶段加入。
>
> 完整实现见 `bridge/src/xiaozhi_bridge/server.py`（V1）→ `bridge/src/xiaozhi_bridge/api/`（V2）。

## 基础信息

- **Base URL**：`http://127.0.0.1:8000`（开发）或 `https://your-domain.com/api`（生产）
- **认证**：V1 无；V2 计划加 JWT
- **数据格式**：JSON
- **CORS**：默认放行 `http://localhost:3000`、`http://localhost:5173`

## 端点（V2 计划）

### Devices 设备

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/devices` | 列出所有设备 |
| `GET` | `/api/devices/{id}` | 设备详情 |
| `POST` | `/api/devices/{id}/reboot` | 重启设备 |

#### `GET /api/devices`

响应：
```json
[
  {
    "id": "esp32-001",
    "name": "客厅小智",
    "mac": "AA:BB:CC:DD:EE:FF",
    "state": "idle",
    "lastSeen": "2026-06-03T10:30:00Z",
    "sessionId": "xiaozhi-abc123def456"
  }
]
```

### Conversations 对话

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/conversations` | 列出对话（分页） |
| `GET` | `/api/conversations/{id}` | 对话详情 |
| `GET` | `/api/conversations/{id}/audio/{turn}` | 音频流 |

### IoT 设备

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/iot` | 列出 IoT 设备 |
| `POST` | `/api/iot/{id}/control` | 控制设备 |
| `POST` | `/api/iot` | 添加设备 |
| `DELETE` | `/api/iot/{id}` | 删除设备 |

#### `POST /api/iot/{id}/control`

请求：
```json
{
  "action": "on",
  "value": null
}
```

响应：
```json
{
  "id": "light-1",
  "state": { "on": true, "brightness": 100 }
}
```

### Settings 设置

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/config` | 获取当前配置 |
| `PATCH` | `/api/config` | 更新配置 |

### Logs 日志

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/logs/stream` | SSE 实时日志流 |

## V1 状态

V1 **没有 HTTP API**，仅 WebSocket。智控台（web/）通过 Vite dev proxy 调用时大部分页面是 mock 数据。

V2 实现路线：
- 用 FastAPI 在 `bridge/src/xiaozhi_bridge/api/` 加 REST 路由
- 把现有 in-memory `self.sessions` 暴露出来
- 用 SQLite 持久化对话历史
