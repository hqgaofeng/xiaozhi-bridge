# 更新日志

> xiaozhi-bridge 版本变更记录
>
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [0.1.5] - 2026-06-03

### V1 cleanup——"把 V1 折腾彻底"

v0.1.2 初版 v1-release-notes 里有几处“计划中的 V2 工具” 被误列成
“V1 已实现”。这次复盘（深度读 bridge / web / docs / deploy 全部
代码）后全面清理。**不是改逻辑**，都是
“代码不动，删死代码 / 修文档”。

### Removed

- `deploy/` 整个目录（Caddyfile、Caddyfile.dev、install.sh、update.sh、systemd/*.service）—— V1 改用 docker compose + 宿主 nginx，deploy/ 里**所有文件都是 scaffold 时代遗留，没人用**。
- `docs/deployment.md`—— 整个文件过时（Caddy + systemd + minimax-cn-api provider）。“V1 部署” 见 `deployment-docker.md`。
- `bridge/src/xiaozhi_bridge/config.py` 里的死字段 `server.cors_origins`、`device.echo_mode`、`mcp.enabled`、`mcp.auto_initialize`——定义了但代码不读。
- `docker-compose.yml` 里的死 volume `bridge-data:/app/data`——源码不写 `/app/data`。
- `bridge/pyproject.toml` 里的死依赖 `edge-tts`（V1 不用 Edge TTS）、`aiohttp`（V1 全部用 httpx）。`aiosqlite` / `PyJWT` / `python-multipart` 移到顶部注释（V2 TODO）。
- `web/package.json` 里的死依赖 `@tanstack/react-query`、`@tanstack/react-router`（V1 全是 mock，不需要）。移到 `"//"` 字段作为 V2 提示。
- `.env.example` 里的 V1 不用字段 `MINIMAX_API_KEY` / `ALIYUN_AK_*` / `PUBLIC_DOMAIN` / `ACME_EMAIL`。
- `docker-compose.dev.yml` 里引用 `deploy/Caddyfile.dev` 的 `caddy` service 块（**V1 删了 caddy**，这 override **会让 dev 跑不起来**——这是上轮埋的 bug，现在修）。
- `bridge-data` / `openclaw-data` 等之前文档里列的“需要备份的 volumes”。
- `docs/v1-release-notes.md` 错列的 "get_time / get_weather / turn_on/off_light"（没实现）、"ASR 触发 get_weather"（没实现）、"React 19 + Vite 7"（实际 React 18 + Vite 5）、"react-router 7"（实际用 Zustand 切页面，不用路由）、"install.sh 脚本"（V1 不跑）、"systemd unit"（V1 不装）。

### Changed

- `pyproject.toml` version `0.1.0` → `0.1.5`。
- `config/config.example.yaml` `base_url` 从 `127.0.0.1:18789` → `host.docker.internal:18789`（docker 内是容器 loopback），加注释明说“docker 外调试用 127.0.0.1”。删 `cors_origins` / `echo_mode` / `mcp.enabled` / `mcp.auto_initialize` 段。
- `web/src/pages/Settings.tsx` 默认值从 `127.0.0.1:18789` / `minimax/MiniMax-M3` → `host.docker.internal:18789` / `openclaw`（跟 v1 实际一致），加 `readOnly`。
- `docs/architecture.md` 架构图 mcp 块 `get_time / get_weather / turn_on/off` → `device tools (3 个)`。§3.1.6 明确桥接内置工具**只**是 3 个 device 工具，`get_time` / `get_weather` / `turn_on/off` 列为 V2 TODO。§4.2 IoT 例子从 `turn_on_light` 换成 `set_volume`。
- `docs/v1-release-notes.md` 全面重写（8526 字节）：去掉“谎话工具”，加 “V1 复盘" 提醒。
- `docs/deployment-docker.md` §4 改 `localhost:8080` → `localhost:5180` / `your-domain.com` → `jarvis.beallen.top`；§6 备份删 Caddyfile / openclaw-data vol；§7 删 “Caddy：直连无 HTTPS”；§8 全部 `docker compose logs openclaw` / `MINIMAX_API_KEY` / `Caddy 拿到证书` / `看 Caddy 反代` 换为 V1 实情（`journalctl` / 宿主机 openclaw 配 / `letsencrypt` 证书路径 / 5180 端口）。
- `README.md` 项目结构图加 `v1-release-notes.md` / `deployment-docker.md`；tests 26 → 28；删 `deploy/`；技术栈表 “反代 Caddy 2” → “宿主 nginx + Let's Encrypt”。
- `web/README.md` 删 "TanStack Query" / "React Router"，明说 V1 用 Zustand 切页面。
- `web/src/lib/api.ts` 保留但加了不调用提示（V1 mock）。Settings 页 6 个输入框加 `readOnly`。

### Notes for V2

- `config.py` 的 `MCPConfig` 类**保留**（V2 要加 pagination cursor / per-session ACL），但运行时不读。
- 智控台 6 页面**全是 mock**——V2 接 FastAPI HTTP API（`/api/devices` 等）。
- 12 个 V2 TODO 选一个开始。

## [0.1.4] - 2026-06-03

### Fixed
- **架构 / 配置 / 协议文档对齐 V1 实际行为**。
  - `docs/architecture.md` **重写**（13045 字节）：架构图从 docker compose 4 容器改为 “bridge/web 容器 + host 上 openclaw / nginx”；LLM 流程加 openclaw agent + sessionKey 隔离说明；删 “bridge 解析 tool_call” 错述；加 “openclaw tool vs bridge MCP” 区分。
  - `docs/config.md` §openclaw 块修正：`base_url` 从 `127.0.0.1:18789` 改为 `host.docker.internal:18789`、`model` 从 `minimax/MiniMax-M3` 改为 `openclaw`（agent target）、`api_key` 改为必填并说明从 gateway.auth.token 拿；加 `user` 跟 `backend_model` 说明；加 “V1 不传 tools[] / system” 说明。
  - `docs/protocol.md` §5（方向说明）、§8.2（不在协议层做的事）、§12（工具实现映射）重写：明确 bridge MCP（get_time / get_weather / turn_on/off_light）是 **bridge 实现**，openclaw agent tool registry 是 **另一套**，bridge 不解析 tool_call。

### Removed
- **`config/openclaw.json.example`**（V1 scaffold 时期的过时文件）：里面说 openclaw 在 docker 里、要填 MiniMax key 到 `providers`、端口 host: 0.0.0.0。V1 实际是 openclaw 在 host 上跑 systemd、MiniMax key 在 openclaw 自己的 plugin 配置里、不需要这个文件。**删了。**

## [0.1.3] - 2026-06-03

### Added
- **`docs/v1-release-notes.md`**：V1 完成清单 + 端到端验证证据（120+ Opus 帧、M3 真返回中文、带会话隔离）。逐项列出 V1 已实现的 8 大模块、12 个 V2 TODO。

### Changed
- **`README.md` 状态从 “V1 开发中” 改为 “V1 已发布 (v0.1.2)”**，加 demo 地址 https://jarvis.beallen.top；特性加 “公网 HTTPS” + “28 测试含 live test” + “隔离会话”。
- **`README.md` 快速开始 §2-5 修订**：删 Caddy 步骤、改成 “宿主 openclaw 改 bind + 宿主 nginx 签证书” 两件，WebSocket 和智控台 demo 地址改到 jarvis.beallen.top / 5180。

## [0.1.2] - 2026-06-03

### Fixed
- **部署到 jarvis.beallen.top 全栈端到端走通**：从公网 `wss://jarvis.beallen.top/xiaozhi/v1/` 走 nginx → bridge → openclaw → M3 返回中文带工具调用的实际响应（5 消息 133 个 Opus 帧）。
- **bridge 容器内 `base_url` 修正**：`config.example.yaml` 默认是 `http://127.0.0.1:18789`，这在容器内是容器自己 loopback（不通）。改为 `http://host.docker.internal:18789`（需在 `docker-compose.yml` 中加 `extra_hosts: host.docker.internal:host-gateway`）。
- **openclaw bind 从 loopback 改为 lan**：默认 openclaw 只听 127.0.0.1，bridge 容器连不上。改为 `lan`（绑 0.0.0.0）。

### Changed
- **`docker-compose.yml` 大改**：
  - 删 caddy service（跟宿主上已有 nginx 抢 80/443 冲突）。
  - web 改 loopback `127.0.0.1:5180:80`（替代 caddy 80 端口）。
  - bridge 加 `extra_hosts: host.docker.internal:host-gateway`。
  - 删 openclaw service（openclaw 在 host 上跑 systemd，不在 docker 里）。
  - 删 openclaw-data / caddy-data / caddy-config volumes。
- **`docs/deployment-docker.md` §2 重写**：原结构里 caddy / 4-container 部署跟新方案不匹配，重写为 5 步（clone / config / 宿主 openclaw / 宿主 nginx / docker up），明确"caddy 已删、改用宿主 nginx"。
- **`.gitignore` 增 `config/openclaw.json`**：防止误把运行时 openclaw 配置 commit 进项目。

### Added
- `docs/deployment-docker.md` 新增 `§2.3` openclaw bind 模式 + 安全性讨论、`§2.4` nginx 反代示例。

## [0.1.1] - 2026-06-03

### Fixed
- **bridge 跟 openclaw 通信协议从错的 Anthropic-style 换成对的 OpenAI-style**
  - 之前 f50970b 推送的版本调 `/v1/messages` 永远 404，LLM 实际没接通。
  - 现在调 openclaw 的 `/v1/chat/completions`，**真 M3 响应**已被测试验证。
- **鉴权头从 `x-api-key` 换成 `Authorization: Bearer <token>`**（openclaw gateway 期望）。
- **model 字段语义变更**：从上游 LLM id (`minimax/MiniMax-M3`) 改成 openclaw agent target (`openclaw`)。
  上游 LLM 由 openclaw 自己选；需要覆盖时用 `x-openclaw-model: minimax/MiniMax-M3-highspeed` header。
- **Session 隔离**：bridge 调 openclaw 时传 `user: "xiaozhi-bridge"`，派生独立 session key
  (`openai-user:xiaozhi-bridge`)，跟 main session 不互串。

### Changed
- `bridge/src/xiaozhi_bridge/llm/openclaw.py` 整文件重写：OpenAI 兼容流式客户端，只收文本不再解析 tool_calls。
- `bridge/src/xiaozhi_bridge/llm/prompts.py` 删 `IOT_CONTROL_TOOL` / `SEARCH_TOOL` / `get_default_tools`：
  web_search 走 openclaw 内置，IoT 走 bridge 的 MCP 通道，LLM 客户端不再负责工具调度。
- `bridge/src/xiaozhi_bridge/server.py` 的 `_process_text` 删 `tool_call` 收集 / 执行分支，简化成
  纯文本流：LLM in → text out → TTS。
- `config/config.example.yaml` 改 `openclaw.model: openclaw`，加 `backend_model` / `user` / `session_key` 字段。
- `bridge/src/xiaozhi_bridge/config.py` 默认 `model: "openclaw"`，新增 `backend_model` / `user` / `session_key` 字段。

### Added
- `bridge/tests/test_openclaw_live.py`：真调 openclaw gateway 的集成测试（需 `OPENCLAW_LIVE_TEST=1` 才跑）。
- `docs/architecture.md` §3.1.5 重写 LLM 客户端说明，强调 agent-target 模式。
- `docs/deployment-docker.md` §2.6：加 "开启 openclaw chatCompletions endpoint" 部署步骤。
- `README.md` 部署步骤加同样提示。

### Removed
- `llm/prompts.py` 里的 `IOT_CONTROL_TOOL`、`SEARCH_TOOL`、`get_default_tools` 全部删除。
- `server.py` 不再 import `LLMTool`、`build_system_prompt`、`get_default_tools`。

### Migration Notes
- **必须**在 openclaw 配置里开启 `gateway.http.endpoints.chatCompletions.enabled: true`，
  并重启 openclaw gateway。否则 bridge 启动后所有 LLM 调用会 401/404。
- `config/config.yaml` 里如果还写 `model: minimax/MiniMax-M3`，需要改为 `model: openclaw`
  （或加 `backend_model: minimax/MiniMax-M3-highspeed` 作为 header 覆盖）。


### Added
- 项目初始化：完整目录结构、文档骨架
- Bridge（Python 桥接服务）：
  - WebSocket server，支持 xiaozhi 协议 v1
  - 协议层：hello/listen/abort/mcp 消息解析，状态机
  - Opus 音频编解码（带 libopus 不可用时的 fallback）
  - ASR 抽象层（mock 实现）
  - TTS 抽象层（mock 实现）
  - LLM 客户端：openclaw gateway 集成
  - MCP JSON-RPC 2.0 端点（initialize / tools/list / tools/call）
  - 内置工具：`self.get_device_status`、`self.audio_speaker.set_volume`、`self.led.set_rgb`
  - 配置管理（Pydantic + YAML）
  - 结构化日志（structlog）
  - 系统 prompt 模板（中文 TTS 友好）
  - 26 个单元/集成测试，全部通过
- Web 智控台（React + shadcn/ui 风格）：
  - 总览、设备、对话、IoT、设置、日志 6 个页面
  - 暗色主题，可切换
  - 侧边栏 + 顶栏布局
  - 可折叠侧边栏
  - 实时日志（V1 mock，V2 接入 SSE）
- 部署：
  - systemd units（xiaozhi-bridge、xiaozhi-web）
  - Caddyfile 反代配置（自动 HTTPS）
  - install.sh / update.sh 一键脚本
- 文档：
  - README.md（项目总览）
  - architecture.md（系统架构详解）
  - protocol.md（xiaozhi WebSocket + MCP 协议）
  - api.md（HTTP API 规范）
  - deployment.md（部署指南）

### TODO（V2+）
- [ ] 真实 ASR 集成（阿里云 / 讯飞 / 腾讯）
- [ ] 真实 TTS 集成（Edge TTS / sherpa-onnx 本地）
- [ ] Opus 编码（TTS → 设备的音频流）
- [ ] 设备端能力反向 MCP（设备 → 桥接 → openclaw）
- [ ] HTTP API（FastAPI）
- [ ] 对话历史持久化（SQLite）
- [ ] Web 智控台真实数据接入
- [ ] 多设备支持
- [ ] OTA 固件升级接口
- [ ] MQTT 协议支持
- [ ] 声纹识别
- [ ] 知识库 / RAG
