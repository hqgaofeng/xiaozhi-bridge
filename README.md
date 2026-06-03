# xiaozhi-bridge

> 替代 [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) 的轻量自建后端
>
> 基于 [openclaw](https://github.com/openclaw/openclaw) + M3，自带 Web 智控台
>
> 目标：单台 1-2G 内存 VPS 稳定运行，**Docker Compose 一键部署**

[![CI](https://github.com/hqgaofeng/xiaozhi-bridge/workflows/CI/badge.svg)](https://github.com/hqgaofeng/xiaozhi-bridge/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)
![Node 22+](https://img.shields.io/badge/node-22+-green.svg)
![Docker](https://img.shields.io/badge/docker-required-blue.svg)

## 项目状态

✅ **V1 已发布**（v0.1.2 → v0.1.5，2026-06-03） — 详见 [docs/v1-release-notes.md](docs/v1-release-notes.md)
✅ **V2 #3 已发布**（v0.2.0，2026-06-03） — FastAPI HTTP API（bridge-api 独立进程，11 个 /api/* 端点，aiosqlite + WAL）
✅ **V2 #4 已发布**（v0.2.1，2026-06-03） — device association：`upsert_device` 接受 `None` 转到 `unknown` 桶；新增 `GET /api/devices/{id}/conversations`；11 个新单测。

**端到端跑通**：
- WebSocket：从公网 `wss://jarvis.beallen.top/xiaozhi/v1/` 连上 xiaozhi-esp32 协议，走 bridge → openclaw → MiniMax-M3，返回中文实际响应（120+ Opus 帧）。
- HTTP API：调 `https://jarvis.beallen.top/api/conversations` 能读真 M3 对话记录。
- 实测两次对话："讲个笑话"→ 程序员笑话、"你好小智"→ "我是贾维斯，不是小智 😄"。

**V1 包含**：WebSocket 协议 / LLM 桥接 / MCP 工具 / Mock ASR+TTS / React 智控台 / Docker Compose / 域名 HTTPS（jarvis.beallen.top）。

**V2 TODO 列表**（12 项）：FastAPI HTTP API ✅ / 对话持久化 ✅ / Web 接真数据 / 真 ASR / 真 TTS / 多设备 / 反向 MCP / OTA / MQTT / 声纹 / RAG / 监控告警备份。

## ✨ 特性

- 🐳 **Docker Compose 一键部署** — 2 个服务（bridge + web）+ 宿主 nginx + Let's Encrypt
- 🪶 **轻量** — 1G 内存 + 1G swap 凑合可跑
- 🔌 **可插拔** — ASR / TTS / LLM 都抽象成接口，配置文件切换 provider
- 🤖 **M3 大脑** — 走 openclaw + MiniMax M3，1M context，工具调用
- 📡 **完整协议** — xiaozhi WebSocket + MCP JSON-RPC 2.0
- 🎨 **现代智控台** — React 19 + TypeScript + Tailwind + shadcn/ui 风格
- 🧪 **28 个测试** — 全绿 ✅（含 1 个真打 openclaw 的 live test）
- 📚 **6 个详细文档** — 架构/协议/API/部署/配置/日志/V1 发布说明
- 🔒 **隔离会话** — `user: xiaozhi-bridge` 派生独立 session，不污染主会话
- 🛡️ **真实部署** — `https://jarvis.beallen.top` 公网可访问

## 🏗️ 架构

```
xiaozhi-esp32 硬件 (ESP32-S3)
    │ WebSocket (Opus + JSON)
    ▼
┌──────────────────────┐
│  bridge              │  桥接服务
│  - WebSocket server  │  (Python 3.12, asyncio)
│  - Opus 音频         │
│  - ASR/TTS 抽象层     │
│  - MCP JSON-RPC 2.0  │
└──────────┬───────────┘
           │ HTTP
           ▼
┌──────────────────────┐
│  openclaw + M3       │  LLM 大脑
│  (LLM 推理/工具调用)  │  (MiniMax M3, 1M context)
└──────────┬───────────┘
           │ HTTP
           ▼
┌──────────────────────┐
│  web 智控台           │  设备管理、对话、IoT
│  (React + shadcn/ui) │
└──────────────────────┘
```

详细架构：[docs/architecture.md](docs/architecture.md)

## 🚀 快速开始

### 前置条件

- Linux / macOS / WSL2
- Docker 24+
- Docker Compose v2+
- 1G+ 内存的 VPS 或本地机器

### 部署

```bash
# 1. 克隆
git clone https://github.com/hqgaofeng/xiaozhi-bridge.git
cd xiaozhi-bridge

# 2. 配置
cp .env.example .env
# 编辑 .env 填入 LOG_LEVEL 等

cp config/config.example.yaml config/config.yaml
# 编辑 config/config.yaml
# ⚠️ openclaw.base_url 默认是 http://host.docker.internal:18789
#    （bridge 容器调宿主上的 openclaw，宿主 openclaw 必须 bind 到 0.0.0.0）
#    openclaw api_key 从宿主的 ~/.openclaw/openclaw.json 里 gateway.auth.token 拿

# 3. 宿主上准备 openclaw（两件必做）
# a) 在 ~/.openclaw/openclaw.json 的 gateway 下加：
#      "http": { "endpoints": { "chatCompletions": { "enabled": true } } }
#      "bind": "lan"
# b) 重启 openclaw gateway（systemctl --user restart openclaw-gateway）
# c) 验证: ss -tlnp | grep 18789   → 应看到 0.0.0.0:18789

# 4. 宿主上准备 nginx + Let's Encrypt（生产）
# 本项目不再起容器内 caddy。参考 docs/deployment-docker.md §2.4 添 nginx conf + 签证书

# 5. 启动
docker compose up -d

# 6. 查看日志
docker compose logs -f bridge
```

**WebSocket 地址**：
- 本地开发：`ws://localhost:8000/xiaozhi/v1/`
- 生产（HTTPS）：`wss://jarvis.beallen.top/xiaozhi/v1/`（demo）

**智控台**：
- 本地开发：http://localhost:5180
- 生产：https://jarvis.beallen.top（demo）

### 开发模式

```bash
# 用 dev compose file（live reload、debug 端口）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# 跑测试
docker compose exec bridge pytest

# 进容器调试
docker compose exec bridge bash
```

## 📁 项目结构

```
xiaozhi-bridge/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── .env.example                # 环境变量模板
├── Dockerfile.bridge           # 桥接服务镜像
├── Dockerfile.web              # 智控台镜像
├── docker-compose.yml          # 生产部署
├── docker-compose.dev.yml      # 开发覆盖
├── .dockerignore
├── .github/
│   ├── workflows/              # CI / Release
│   │   ├── ci.yml
│   │   └── release.yml
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── bridge/                     # Python 桥接服务（WS + V2 #3 HTTP API）
│   ├── pyproject.toml
│   ├── src/xiaozhi_bridge/     # 源码
│   │   ├── api/                # V2 #3 FastAPI HTTP API (bridge-api 进程)
│   │   │   ├── __init__.py     # 架构选型说明 (Option C：跨进程 sqlite)
│   │   │   ├── __main__.py     # python -m xiaozhi_bridge.api 入口
│   │   │   ├── db.py           # aiosqlite + WAL + 6 表
│   │   │   └── main.py         # FastAPI app + 11 routes
│   │   ├── asr/ tts/ llm/ mcp/ protocol/  # V1 模块
│   │   ├── server.py           # bridge WS 进程，集成写 db
│   │   └── config.py
│   └── tests/                  # 53 个测试（27 V1 + 15 V2 #3 + 11 V2 #4）
├── web/                        # React 智控台（V1 mock，V2 #5 接 /api/*）
│   ├── package.json
│   ├── src/
│   └── public/
├── docs/                       # 文档
│   ├── architecture.md         # 架构设计
│   ├── protocol.md             # xiaozhi WebSocket 协议
│   ├── api.md                  # HTTP API（V2 #3 + V2 #4 已实现）
│   ├── deployment-docker.md    # Docker Compose 部署
│   ├── config.md               # 配置说明
│   ├── changelog.md            # 版本变更
│   └── v1-release-notes.md     # V1 + V2 #3 + V2 #4 发布说明
└── config/
    └── config.example.yaml
```

## 🛠️ 技术栈

| 组件 | 选型 | 备选 |
|---|---|---|
| 桥接服务 | Python 3.12 + asyncio | Node.js |
| WS 框架 | websockets | aiohttp |
| LLM 客户端 | openclaw gateway | 直接 MiniMax API |
| 前端 | React 18 + Vite 5 + TypeScript | SvelteKit |
| 样式 | Tailwind 3 + shadcn 风格 | shadcn-svelte |
| 状态 | Zustand | Redux |
| 反代 | 宿主 nginx + Let's Encrypt | Caddy |
| 部署 | Docker Compose | systemd |
| CI | GitHub Actions | — |

## 📚 文档

- 📐 [架构设计](docs/architecture.md)
- 📡 [协议规范](docs/protocol.md)
- 🔌 [HTTP API](docs/api.md)
- 🚀 [部署指南](docs/deployment.md)
- ⚙️ [配置说明](docs/config.md)
- 📝 [更新日志](docs/changelog.md)

## 🤝 贡献

欢迎提 Issue 和 PR！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 📜 许可证

[MIT](LICENSE)

## 🙏 致谢

- [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — 固件
- [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) — 协议参考
- [openclaw](https://github.com/openclaw/openclaw) — LLM 运行时
- [MiniMax M3](https://minimaxi.com) — LLM 大脑
