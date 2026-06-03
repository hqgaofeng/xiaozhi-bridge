# 更新日志

> xiaozhi-bridge 版本变更记录
>
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased] - V1 开发中

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
