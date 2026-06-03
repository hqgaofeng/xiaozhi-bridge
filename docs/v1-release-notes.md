# V1 Release Notes

> **版本：** v0.1.5
> **发布日期：** 2026-06-03
> **GitHub：** https://github.com/hqgaofeng/xiaozhi-bridge
> **演示地址：** https://jarvis.beallen.top

V1 目标：**把一只 xiaozhi-esp32 设备能连上 LLM 跑通端到端**，所有模块**真实工作**（不是只搭骨架）。

> 本文档**是 v0.1.5 cleanup 之后的真实清单**。v0.1.2 的初版有几处把 "plan 里的
> V2 工具" 误写成 "V1 已实现"，已经在 v0.1.5 复盘后修掉。详见 [changelog.md](changelog.md)
> v0.1.5 条目。

---

## 1. V1 已实现的所有功能（事实清单）

### 1.1 协议层（xiaozhi-esp32 兼容）

| 功能 | 实现 | 测试 |
|---|---|---|
| WebSocket 服务端 (`ws://0.0.0.0:8000/xiaozhi/v1/`) | `server.py` 498 行 | ✅ 28 pytest + 实测连接 |
| 路径过滤（其他路径 404） | `server.py` `process_request` | ✅ 端到端 |
| Hello 握手（version / features / transport / audio_params） | `protocol/messages.py` | ✅ |
| Listen 状态机（`start` / `stop` / `detect` 模式） | `protocol/states.py` 113 行 | ✅ |
| TTS 状态机（`start` / `sentence_start` / `stop`） | `protocol/states.py` | ✅ |
| 设备消息：`hello` / `listen` / `abort` / `mcp` | `protocol/messages.py` 185 行 | ✅ 8 协议测 |
| 服务端消息：`hello` / `stt` / `llm` / `tts` / `mcp` / `system` | `protocol/messages.py` | ✅ |
| 二进制 Opus 帧收发（frame_duration=60ms, 16kHz, mono） | `protocol/audio.py` 146 行 | ✅ 实测 120+ 帧 |
| State transitions（listening→thinking→speaking→idle） | structlog 事件 | ✅ |
| Session 管理（per-connection 状态隔离） | `server.py` SessionContext 类 | ✅ |
| 错误恢复（device.auth_token 失败、TTS 异常不杀进程） | `server.py` | ✅ |
| `process_request` 路径白名单 | `server.py` | ✅ |

### 1.2 LLM 桥接（openclaw agent 客户端）

| 功能 | 实现 | 验证 |
|---|---|---|
| OpenAI 协议 POST `/v1/chat/completions` | `llm/openclaw.py` 180 行 | ✅ |
| Bearer token 鉴权（gateway.auth.token） | `openclaw.py` | ✅ |
| **Agent target 模式**：`model: "openclaw"` | `openclaw.py` | ✅ 真 M3 返回 |
| **Backend override header**：`x-openclaw-model` | `openclaw.py` | ✅ |
| **用户会话隔离**：`user: "xiaozhi-bridge"` → openclaw 派生独立 session | `openclaw.py` | ✅ 不污染主会话 |
| **流式响应**（SSE → 拼成完整文本） | `openclaw.py` | ✅ |
| **不传 `tools[]`**（openclaw 自有 tool registry） | `openclaw.py` 注释 + 拒绝逻辑 | ✅ |
| **不传 system**（走 openclaw agent 自己的 prompt） | `openclaw.py` | ✅ |
| `prompts.py` 参考 voice-assistant 模板（**不自动发送**） | `llm/prompts.py` | ✅ |
| 错误处理：401/超时/网络错（返 fallback 短句） | `openclaw.py` | ✅ |
| **Live test**（真打 openclaw gateway） | `tests/test_openclaw_live.py` | ✅ `OPENCLAW_LIVE_TEST=1` 跳过 + 28 套通过 |

### 1.3 工具调用（MCP over WebSocket）

| 功能 | 实现 | 验证 |
|---|---|---|
| MCP JSON-RPC 2.0 server（`initialize` / `tools/list` / `tools/call`） | `mcp/server.py` 171 行 | ✅ 7 单元测 |
| 设备内置工具 `self.get_device_status` | `mcp/tools.py` | ✅ 7 测 |
| 设备内置工具 `self.audio_speaker.set_volume` | `mcp/tools.py` | ✅ |
| 设备内置工具 `self.led.set_rgb` | `mcp/tools.py` | ✅ |
| Tool JSON Schema 严格定义（OpenAI function calling 格式） | `mcp/tools.py` | ✅ |
| WebSocket 上 `mcp` response 推送给设备 | `protocol/messages.py` | ✅ |

> ⚠️ **V1 没做**（被早期 v1-release-notes 误列）：`get_time` /
> `get_weather` / `turn_on/off_light` 这些属于 V2（V1 的 mcp/tools.py 只
> 3 个 device 工具）。详见 [changelog.md](changelog.md) v0.1.5。

### 1.4 ASR / TTS（Mock + 扩展点）

| 功能 | 实现 | 验证 |
|---|---|---|
| ASR 抽象基类（`ASRBase`） | `asr/base.py` 97 行 | ✅ |
| **Mock ASR**：random/fixed 模式（8 个中文短语随机 / 固定） | `asr/mock.py` 62 行 | ✅ 3 测 |
| TTS 抽象基类（`TTSBase`） | `tts/base.py` 85 行 | ✅ |
| **Mock TTS**：silence / 440Hz tone（opuslib 真编 Opus 60ms 帧） | `tts/mock.py` 64 行 | ✅ 真发 120+ 帧 |
| **可插拔**：换真实 ASR/TTS 只需实现 `ASRProvider` / `TTSProvider` | `__init__.py` factory | ✅ |
| 注册表 / `get_asr(name)` / `get_tts(name)` | `asr/base.py` + `tts/base.py` | ✅ |

### 1.5 配置系统

| 功能 | 实现 | 验证 |
|---|---|---|
| YAML 配置（`config/config.yaml`） | `config.py` | ✅ |
| 环境变量 override（`XIAOZHI_OPENCLAW__BASE_URL`） | `config.py` Pydantic | ✅ |
| Pydantic 校验（`BaseSettings`） | `config.py` | ✅ |
| **敏感配置不 commit**（`.gitignore` 含 `config/config.yaml` + `config/openclaw.json` + `.env`） | `.gitignore` | ✅ |
| 配置示例文件（`config.example.yaml`） | `config/config.example.yaml` | ✅ |
| 配置单元测试 | `tests/test_config.py` | ✅ 3 测 |

### 1.6 智控台 Web（React + TypeScript）—— **V1 全是 mock**

| 功能 | 实现 | 状态 |
|---|---|---|
| **React 18** + **Vite 5** + TypeScript 5.6 + Tailwind 3 | `web/package.json` | ✅ 构建过 |
| 6 个页面：Dashboard / Devices / Conversations / IoT / Settings / Logs | `web/src/pages/*.tsx` | ✅ **UI 占位** |
| 页面切换（Zustand `useUIStore`，**不是路由**） | `web/src/App.tsx` + `lib/store.ts` | ✅ |
| Sidebar + Topbar 布局 | `web/src/components/*` | ✅ |
| Toast（Sonner） | `web/src/App.tsx` | ✅ |
| `lib/api.ts` HTTP client 框架（**V1 没被任何页面调用**） | `web/src/lib/api.ts` | ✅ 占位 |
| `lib/utils.ts`（cn / formatDate / formatRelative） | `web/src/lib/utils.ts` | ✅ |
| Vite dev proxy（`/api/*` + `/xiaozhi/*`） | `web/vite.config.ts` | ✅ |
| Vite build 产出静态文件（Dockerfile.web 容器内置 Caddy 服务） | `Dockerfile.web` | ✅ |
| **真数据接入** | — | ⏳ V2 TODO |

### 1.7 部署（Docker Compose + 宿主 nginx + Let's Encrypt）

| 功能 | 实现 | 验证 |
|---|---|---|
| `docker-compose.yml`（bridge + web 两容器） | `docker-compose.yml` | ✅ |
| bridge `extra_hosts: host.docker.internal:host-gateway` | `docker-compose.yml` | ✅ |
| web 容器内置 Caddy 服务静态文件 | `Dockerfile.web` | ✅ |
| **域 名 HTTPS**：jarvis.beallen.top（Let's Encrypt 证书） | `/etc/nginx/conf.d/jarvis.beallen.top.conf` | ✅ 200 |
| nginx 反代：80→301→443 / /→web / /xiaozhi/→bridge ws / /api/→bridge / /health | nginx conf | ✅ 实测 |
| 公网端到端：`wss://jarvis.beallen.top/xiaozhi/v1/` | — | ✅ M3 真返回 |
| 配置文档：`docs/deployment-docker.md`（5 步走完） | — | ✅ |

> V1 **不**在项目仓库里管 caddy / systemd / install 脚本——这些之前是
> 早期 scaffold 时代遗留，v0.1.5 cleanup 已删除（见 [changelog.md](changelog.md)）。

### 1.8 运维

| 功能 | 实现 | 验证 |
|---|---|---|
| structlog 结构化日志（JSON / console） | `utils/logging.py` | ✅ |
| `pytest` 28 测试通过 | `bridge/tests/` | ✅ 0.45s |
| Live test（真打 openclaw） | `tests/test_openclaw_live.py` | ✅（需 env var 启用） |
| CI（ruff / mypy / pytest / build / docker build） | `.github/workflows/ci.yml` | ✅ |
| Release workflow（构建 + 推 ghcr.io） | `.github/workflows/release.yml` | ✅ |

---

## 2. V1 端到端跑通的证据

**实测命令**（2026-06-03 07:48，从公网）：

```python
# wss://jarvis.beallen.top/xiaozhi/v1/
# hello 握手 → listen start → 100 字节假音频 → listen stop
# 收 TTS 文本 + Opus 帧
```

**结果**：
- `json_msgs=5`
- `opus=120`
- `text='现在是 **2026-06-03 05:19 UTC**（布法罗当地时间凌晨 1:19 AM）。'`

**链路**：ESP32 协议 → nginx（443 TLS）→ bridge (8000) → openclaw (18789) → MiniMax-M3 → 流式文本 → bridge 拼句 → TTS 编码 Opus → 推回设备。

**会话隔离**：`user: xiaozhi-bridge` 派生 `openai-user:xiaozhi-bridge` 独立 session key，**完全独立于**你跟我对话用的 `agent:default-main:openai-user:8682984776` 主会话。

---

## 3. V1 显式**没**做的（12 个 V2 TODO）

1. **真 ASR**（接 funasr / sherpa-onnx / 阿里云 ASR）
2. **真 TTS**（接 edge-tts / 火山引擎 / GPT-SoVITS）
3. **FastAPI HTTP API**（V1 没有 `/api/devices` 之类 REST 端点）
4. **SQLite/Postgres 对话持久化**
5. **Web 接真数据**（智控台 6 页面都是 mock）
6. **多设备管理**（V1 是单连接/单 session）
7. **反向 MCP**（openclaw 主动调 ESP32 上的传感器/动作）
8. **OTA 固件更新**
9. **MQTT 桥接**
10. **声纹识别**（说话人识别）
11. **RAG / 知识库**
12. **其他**：Prometheus metrics、告警、备份脚本

**V1 显式没做的工具**（在 MCP 模块里，**没出现在代码里**）：
- `get_time` / `get_weather` / `turn_on/off_light` —— V2 TODO（在 V1 文档里
  被错误列过，v0.1.5 cleanup 后修掉）

---

## 4. Git 提交历史

```
d850b49  feat: V1 全栈部署到 jarvis.beallen.top (HTTPS)         ← 0.1.2
ee61068  fix: bridge→openclaw 用 OpenAI 协议 + agent target     ← 0.1.1
f50970b  fix: V1 跑通 + 修洞（opuslib 3.0、websockets v16、TTS Opus 编码...）
542ea17  docs: add Docker Compose deployment guide
ca3a86a  feat: initial V1 scaffold of xiaozhi-bridge
```

（v0.1.3 / v0.1.4 / v0.1.5 文档清理在 v0.1.5 之后）

---

## 5. 怎么自己复现端到端测试

```bash
cd /root/projects/xiaozhi-bridge/bridge
source .venv/bin/activate

# 单元 + live 测试
pytest                                          # 28 passed
OPENCLAW_LIVE_TEST=1 pytest test_openclaw_live.py

# 真打公网
python -c "
import asyncio, json, websockets
async def t():
    async with websockets.connect('wss://jarvis.beallen.top/xiaozhi/v1/') as ws:
        await ws.send(json.dumps({'type':'hello','version':1,'features':{'mcp':True},'transport':'websocket','audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}))
        sid=json.loads(await asyncio.wait_for(ws.recv(),5))['session_id']
        await ws.send(json.dumps({'session_id':sid,'type':'listen','state':'start','mode':'auto'}))
        await ws.send(b'\\x00\\x00'*100)
        await ws.send(json.dumps({'session_id':sid,'type':'listen','state':'stop'}))
        n=0; done=False
        while not done:
            r=await asyncio.wait_for(ws.recv(),30)
            if isinstance(r,bytes): n+=1
            else:
                d=json.loads(r)
                if d.get('type')=='tts' and d.get('state')=='stop': done=True
        print(f'opus frames: {n}')
asyncio.run(t())
"
```

---

**V1 ✅ 完成**。等你选 V2 TODO 第一个做。
