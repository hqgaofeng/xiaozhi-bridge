# xiaozhi-bridge

> 替代 [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) 的轻量自建后端
>
> 基于 [openclaw](https://github.com/openclaw/openclaw) + M3，自带 Web 智控台
>
> 目标：单台 1-2G 内存 VPS 稳定运行，**Docker Compose 一键部署**

[![CI](https://github.com/yourusername/xiaozhi-bridge/workflows/CI/badge.svg)](https://github.com/yourusername/xiaozhi-bridge/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)
![Node 22+](https://img.shields.io/badge/node-22+-green.svg)
![Docker](https://img.shields.io/badge/docker-required-blue.svg)

## 项目状态

🚧 **V1 开发中** — 详见 [docs/changelog.md](docs/changelog.md)

## ✨ 特性

- 🐳 **Docker Compose 一键部署** — 3 个服务（openclaw + bridge + web）+ Caddy 反代
- 🪶 **轻量** — 1G 内存 + 1G swap 凑合可跑
- 🔌 **可插拔** — ASR / TTS / LLM 都抽象成接口，配置文件切换 provider
- 🤖 **M3 大脑** — 走 openclaw + MiniMax M3，1M context，工具调用
- 📡 **完整协议** — xiaozhi WebSocket + MCP JSON-RPC 2.0
- 🎨 **现代智控台** — React 18 + TypeScript + Tailwind + shadcn/ui 风格
- 🧪 **26 个测试** — 全绿 ✅
- 📚 **6 个详细文档** — 架构/协议/API/部署/配置/日志

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
git clone https://github.com/yourusername/xiaozhi-bridge.git
cd xiaozhi-bridge

# 2. 配置
cp .env.example .env
# 编辑 .env 填入 MINIMAX_API_KEY 等

cp config/config.example.yaml config/config.yaml
# 编辑 config/config.yaml

# 3. 修改 Caddy 域名（生产）
# 编辑 deploy/Caddyfile，把 YOUR_DOMAIN 改成你的域名

# 4. 启动
docker compose up -d

# 5. 查看日志
docker compose logs -f bridge
```

**WebSocket 地址**：
- 本地开发：`ws://localhost:8000/xiaozhi/v1/`
- 生产（HTTPS）：`wss://your-domain.com/xiaozhi/v1/`

**智控台**：
- 本地开发：http://localhost:8080
- 生产：https://your-domain.com

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
├── bridge/                     # Python 桥接服务
│   ├── pyproject.toml
│   ├── src/xiaozhi_bridge/     # 源码
│   └── tests/                  # 26 个测试
├── web/                        # React 智控台
│   ├── package.json
│   ├── src/
│   └── public/
├── docs/                       # 文档
│   ├── architecture.md
│   ├── protocol.md
│   ├── api.md
│   ├── deployment.md
│   ├── config.md
│   └── changelog.md
├── deploy/                     # 部署配置
│   ├── Caddyfile
│   ├── Caddyfile.dev
│   ├── systemd/                # 传统部署（无 Docker）
│   └── scripts/
└── config/
    └── config.example.yaml
```

## 🛠️ 技术栈

| 组件 | 选型 | 备选 |
|---|---|---|
| 桥接服务 | Python 3.12 + asyncio | Node.js |
| WS 框架 | websockets | aiohttp |
| LLM 客户端 | openclaw gateway | 直接 MiniMax API |
| 前端 | React 18 + Vite + TypeScript | SvelteKit |
| 样式 | Tailwind + shadcn 风格 | shadcn-svelte |
| 状态 | Zustand | Redux |
| 反代 | Caddy 2 | nginx |
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
