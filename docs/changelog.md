# 更新日志

> xiaozhi-bridge 版本变更记录
>
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Done since 0.2.1
- V2 #4 SQLite conversation persistence refinement — `upsert_device`
  and `open_session` now accept `device_id=None` (firmware that
  forgot to send a Device-Id header gets bucketed under a synthetic
  "unknown" device row, so /api/devices stops appearing empty for
  misbehaving firmware). New `GET /api/devices/{id}/conversations`
  route for per-device history. 11 new unit tests in
  tests/test_db.py + tests/test_api.py. Bridge tests 42 → 53
  (1 live-test skipif unchanged).
- V2 #4 post-release polish (still 0.2.1, no version bump):
  `BridgeDB.record_conversation` now applies the same
  `device_id or "unknown"` rule as `upsert_device` so the
  conversation rows under the unknown bucket are queryable via
  `/api/devices/unknown/conversations`; `_get_header` in
  `bridge/server.py` now handles the websockets 16+ API where
  `ws.handshake` is a method (not a property); new
  `scripts/e2e_smoke.py` is a 5-case live e2e harness.
  Bridge tests 53 → 57.
- V2 #5 admin console wired to /api/* (web 0.2.0): all 5 page
  components (Dashboard / Devices / Conversations / IoT /
  Settings) now fetch real data from bridge-api instead of
  hardcoded mocks. New `useApi<T>()` hook for uniform
  loading / error / refresh state; per-page error blocks
  instead of blanking the whole screen on one bad endpoint;
  per-device drill-down from the Devices page; K-V editor
  for /api/config; IoT devices show live on/off state with
  optimistic controls. Vite dev proxy target fixed
  (was pointed at bridge WS on 8000, now points at
  bridge-api on 8001). Type-check 0 errors; production
  build 0 errors. Logs page kept as V1 mock (server
  /api/logs/stream is still 501). Released as
  `[0.2.0-web]`.

### Next
- V2 #1 real ASR / V2 #2 real TTS (the V2 #5 admin console
  is now in place, so the real-time ASR/TTS swap can target
  a UI that already shows real conversations).
- V2 #6 multi-device, V2 #7 reverse MCP, V2 #8 OTA, V2 #9 MQTT,
  V2 #10 voiceprint, V2 #11 RAG, V2 #12 monitoring/alerting/backup.

## [0.2.0-web] - 2026-06-03

### V2 #5 admin console wired to /api/* (web 0.2.0)

这是 web 0.2.0（web 独立 semver；bridge 仍是 0.2.1）。
V2 #3 解锁了“接真数据”路径，V2 #5 是真正的实现：在 5 个
page 上把 hardcoded mock 全部替换为从 bridge-api fetch 的真数据。

### Added

- `web/src/lib/useApi.ts` — 泛型数据获取 hook。提供
  `{ data, error, loading, refresh }` 四个状态，避免每个 page
  重复 useEffect/useState。挂载时拉一次，`refresh()` 手动重
  拉，组件卸载时取消 in-flight 请求。

- 5 个 page 全部接真数据：
  - **Dashboard** — 4 个 stat 卡 从 /api/devices (在线数) +
    /api/conversations (最近 100 条数) + /api/iot (在线数)
    拿真数。
  - **Devices** — 列表接 /api/devices；点任一设备跳转
    /api/devices/{id}/conversations 查看该设备历史。
  - **Conversations** — 接 /api/conversations，加
    `?deviceId=...` 过滤。带搜索框 client-side filter
    (按文本)。
  - **IoT** — 接 /api/iot + /api/iot/{id}/control POST，
    翻状态后 refresh。
  - **Settings** — 接 /api/config GET + PATCH，K-V 编辑器
    (任意 JSON 兼容 key/value，保存后发 PATCH 覆盖)。

### Changed

- **Vite dev proxy** (`web/vite.config.ts`) `/api` target 从
  127.0.0.1:8000 (bridge WS) 改为 127.0.0.1:8001
  (bridge-api)。之前的配置是错的——bridge WS 进程不接
  HTTP GET，只是巧合性不会让 8000 响应 /api。
  `/xiaozhi` 仍走 8000 (WebSocket upgrade)。
- `web/src/lib/api.ts` Conversation interface 补 sessionId、
  llmStatus 字段（之前漏了，跟 server 端 schema 不一致）。
  controlIot 签名收紧为 `{ action: 'on'\|'off'; value? }`
  object 参数（之前是 positional，调用容易错位）。
- `web/package.json` version 0.1.0 → 0.2.0。

### Known gaps (V2 #6+ follow-ups)

- **Logs page** 仍是 V1 `setInterval` 假流。server 端
  /api/logs/stream 仍是 501/SSE 椎，留给 V2 #6。
- 没有 SWR / react-query 缓存，5 page 各自 fetch。够用但不
  高效。V2 #6 上 react-query。
- WebSocket 实时推送 (设备 online 状态、实时对话推送) 还没
  接。V2 #6 加 @tanstack/react-query + ws hook。



## [0.2.1] - 2026-06-03

### V2 #4 SQLite conversation persistence

把 v0.2.0 遗漏的 device association 补上：之前 firmware 不发
`Device-Id` header 时 `open_session` 跳过了 `upsert_device`，
`/api/devices` 永远显示 `[]`、conversations 的 `device_id` 永远是
空字符串。V2 #4 改用 synthetic `"unknown"` 桶来收容“匿名”会话，
让这种“ 失联设备”能 可见且可查。

### Changed

- `BridgeDB.upsert_device(device_id)` now accepts `None` and stores
  it as `"unknown"`. This is so the devices row is always present
  (it's the parent of conversations via FK, and the source of truth
  for /api/devices).
- `BridgeDB.open_session(device_id)` always calls `upsert_device`
  now, regardless of whether device_id is truthy.

### Added

- New route `GET /api/devices/{device_id}/conversations?limit=50`.
  Returns the same shape as `GET /api/conversations?deviceId=...`
  but scoped to a single device. `?limit` clamps to [1, 500].
- `tests/test_db.py` — 8 direct BridgeDB unit tests, including the
  "open_session without device_id still creates a device row"
  contract and "device_id is None on a conversation is stored as
  deviceId='' in the API response".
- 3 new tests in `tests/test_api.py` for the per-device
  conversations route (empty, seeded, limit).

### Cleaned up

- `config/config.yaml` (live, gitignored): removed `device.echo_mode`
  (V1 cleanup deleted the code but left the dead yaml key) and
  `mcp.enabled` / `mcp.auto_initialize` (V1 cleanup had already
  moved mcp config into code; the yaml keys were dead). The
  yaml-stable `mcp: {}` placeholder from V1 cleanup is kept.

### Fixed (post-release follow-ups landed in the v0.2.1 line)

- **`_get_header` failed on websockets 16+** (commit `2cd05db`):
  V2 #3 wrote the helper against the websockets 14-15 API where
  `ws.handshake` is a *property* returning the parsed `Request`.
  In 16+ `ws.handshake` is a *method* that performs the upgrade,
  and the parsed request lives at `ws.request`. The old code did
  `getattr(ws, "handshake").headers` on the bound method, which
  raised `AttributeError` and was silently swallowed by the
  fall-through path, so `device_id` was always `None` for any
  modern websockets client. The V2 #3 e2e missed this because
  the e2e client didn't send a `Device-Id` header (so the NULL
  was "expected"). V2 #4 made the bug visible by actually
  reading the device id. Helper now probes all three surfaces
  (legacy / 14-15 / 16+) with a `callable()` check to
  distinguish property from method. 4 new tests in
  `tests/test_pipeline.py`.

- **`record_conversation` didn't apply the unknown bucket**
  (commit `9bb3e80`): the V2 #4 gap surfaced by the live e2e
  — `upsert_device(None)` wrote a row under id `"unknown"` but
  `record_conversation(device_id=None)` still wrote the
  conversation row with `device_id=NULL`. The two tables
  drifted: `/api/devices` had an `unknown` row, but
  `/api/devices/unknown/conversations` returned `[]` because
  no conversation row carried the bucket id. Fix: same
  `effective_device_id = device_id or "unknown"` rule as
  upsert_device. The `unknown` filter in `/api/conversations`
  and the new `/api/devices/unknown/conversations` route both
  return the right rows now. 1 test updated in `tests/test_db.py`.

### Added (post-release follow-up)

- **`scripts/e2e_smoke.py`**: a 5-case e2e harness against the
  live bridge (hello → listen → STT → LLM → TTS → tts.stop,
  then assert the conversation row landed in sqlite). Catches
  things pytest can't: library version drift, live openclaw
  behavior, real db commit timing. Not a CI test (it needs
  the live bridge + openclaw); run it after a rebuild to
  confirm production is healthy. Run with
  `python scripts/e2e_smoke.py` from the project root. The
  script discovered 4 bugs during the V2 #4 live deploy
  (recv-timeout too short, race against db commit, wrong
  default DB_PATH for the docker named volume, and the
  unknown-bucket gap above) — most of which pytest would
  never have caught. See README project structure for
  details; see `docs/deployment-docker.md` §4 for the
  verification step that calls this.

## [0.2.0] - 2026-06-03

## [0.2.0] - 2026-06-03

### V2 #3 FastAPI HTTP API

解锁 v0.1.5 智控台 6 页面的" 接真数据" 路径：V2 #3 之前 web/ 下所有
GET/POST 都是 mock，现在 bridge-api 进程已经在 8001 端口提供
11 个 HTTP 端点，智控台可以一边（V2 #5）替换 fetch mock 为
fetch /api/*。

### Added

- 新模块 `bridge/src/xiaozhi_bridge/api/`：FastAPI 应用。
  - `__init__.py`：说明跨进程 sqlite 架构选型
  - `__main__.py`：`python -m xiaozhi_bridge.api` 入口
  - `db.py`：aiosqlite + WAL 模式 + 6 张表（devices, sessions,
    conversations, iot_devices, iot_state, config_kv） + seed
    2 个 demo IoT 设备
  - `main.py`：create_app + lifespan 上下文 + 11 个 /api/* 路由
- bridge 服务侧集成：每个 session 状态转换调
  `session.persist_state(db)`、每个完成的 turn 调
  `db.record_conversation(stt, assistant_text, status)`。所有
  db 写包在 best-effort try/except，**sqlite 失败不破坏 WebSocket
  热路径**。
- docker-compose：新增 `bridge-api` service（127.0.0.1:8001）、
  共享 `bridge-data` named volume。
- Dockerfile.bridge：`RUN mkdir -p /app/data && chown app:app` 在
  `USER app` 之前——为让非 root 进程能写 sqlite。
- nginx conf：`/api/` 反代从 8000 改为 8001，加 `proxy_buffering
  off` + 长 read_timeout 支持 SSE。
- pyproject：加 `fastapi>=0.115` / `uvicorn[standard]>=0.30` /
  `aiosqlite>=0.20`。
- 测试：bridge/tests/test_api.py 15 个 TestClient 用例，27→42
  总数。

### Routes

- `GET    /api/health`              — liveness probe
- `GET    /api/devices`             — 设备列表（联接活跃 session）
- `GET    /api/devices/{id}`        — 设备详情
- `POST   /api/devices/{id}/reboot` — V1 返 501（V2 接入 WS abort）
- `GET    /api/conversations`       — 对话列表（?deviceId, ?limit）
- `GET    /api/conversations/{id}`  — 单个对话详情
- `GET    /api/iot`                 — IoT 设备列表
- `POST   /api/iot/{id}/control`    — IoT 控制（V1 改 db，V2 接 MCP）
- `GET    /api/config`              — 配置获取（V1 返空）
- `PATCH  /api/config`              — 配置写（V1 存 db 不应用）
- `GET    /api/logs/stream`         — SSE 日志流（V1 heartbeat 占位）

### Architecture 决策

bridge-api **不跟 bridge 共享内存**——它们是两个独立进程，**通过
sqlite + WAL 模式交换状态**。这是 V2 #3 计划里"Option C"。
理由：

- 不需要 RPC/MessageBus（额外运行时依赖）
- V2 #4 SQLite 对话持久化可以**复用**同一套 schema（不需要为
  API 另起一套）
- bridge 进程崩溃时 bridge-api 仍可读历史（反过来也）
- 唯一代价：bridge 写的状态到 API 看到之间最多 ms 级延迟

### End-to-end 验证

- 公网 `https://jarvis.beallen.top/api/health` → 200
- 公网 `wss://jarvis.beallen.top/xiaozhi/v1/` 跑完一个完整 turn
  （STT"讲个笑话"→ M3 返程序员笑话 + STT"你好小智"→ M3 返
  "我是贾维斯"），**2 条记录都进了 sqlite**，从
  `https://jarvis.beallen.top/api/conversations` 读到。

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
