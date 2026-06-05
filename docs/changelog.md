# 更新日志

> xiaozhi-bridge 版本变更记录
>
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.2.12] - 2026-06-05

### V2 #7 复盘**修**补**: 9 个**深**度**审**视**找**出**的** bug + 13 个**修**复**测**试**

本**次**从**头**读**代**码**深**度**审**视** V2 #7 反**向** MCP 完整**实**现**，**找**出**了** V2 #7 多个**有**实**际**影**响**的** bug**，**全**是** "**调**用**了**但**没**有**被**测**试**覆**盖**"** 的**类**型**：

**Bug 1 - `for/else` 语**法**诡**计****

V2 #7 _process_text 用**了** `for/else` 结**构**，**意**图**是** "**内**层**流**不**用** break 退**出** =**文**本**完**成**"**，**但**三**种** break 条**件**都**会**跳**过** else**，**导**致** else 分**支**几**乎**不**会**触**发**。**改**为**显**式** `tool_dispatched` flag**，**消**除**暗**示**性**路**径**。

**Bug 2 - `_build_payload` 丢**失** tool_calls / tool_call_id / name**

V2 #7 修**改**让** openclaw **收**到** `tools` 参**数**，**但**对**于** `messages` 中**已**经**有** `tool_calls` 字**段**的** assistant turn 和** `tool_call_id` / `name` 字**段**的** tool result，**只**发**了** `role + content`**。**这**意**味**着** openclaw 收**到** assistant 调**用**工**具**的** turn 时**不**知**道**有** tool_call，**tool result 收**到**时**不**知**道**在**回**答**哪**个** call。**修**法**：在** `_build_payload` 中**添**加**三**个**字**段**转**换**：
- `assistant` + `tool_calls` → `entry["tool_calls"]`
- `tool` + `tool_call_id` → `entry["tool_call_id"]`
- `tool` + `name` → `entry["name"]`

**Bug 3 - ESP32_NAME_MAP 是** dead code**（**注**册**的**就**是** esp32 名**字**）**

V2 #7 注**册** DeviceToolHandler 时** `name` 用**了** esp32 端**名**字**（**`self.audio_speaker.set_volume`**），**但** ESP32_NAME_MAP 把** `self.audio_speaker.set_volume` 映**射**到** `self.audio_speaker.set_volume`（**自**己**映**自**己**）**。**改**为**注**册**时**用**友**好**名**字**（**`set_volume`**）+ **ESP32_NAME_MAP 翻**译**成** esp32 名**字**。

**Bug 4 - `_register_device_tools` 全**局**覆**盖** race condition**

新**会**话**调**用** `_register_device_tools` 时** `register_tool` 直**接**覆**盖** `_REGISTRY[handler.name]`，**旧**的** DeviceToolHandler 仍**然**在** _REGISTRY 里**，**但**带**有**旧**的** ws/session 闭**包**。**如**果**两**个**会**话**并**发**，旧**会**话**触**发** tool 调**用**会**走**新**的** ws/session（**因**为**新**的**覆**盖**了**旧**的**）**。**修**法**：在**每**个**会**话**里**追**踪** `_session_tool_owners[session_id] = owned_tools`，**在** finally **块**调**用** `_cleanup_session_tools(session_id)` 解**绑**该**会**话**注**册**的**所**有**工**具**。**这**是** V2 #7.7 per-session MCP server 的**前**置**修**复**。

**Bug 5 - `_handle_mcp` response "id" 匹**配**错**误** log 是** warning 不**是** debug**

`_handle_mcp` 第**二**个** case（response）**中**，**如**果** `pending_mcp_calls.pop()` 返**回** None 或** future.done()，**打**印** `mcp.unknown_response` warning。**这**会**干**扰**生**产** log —— esp32 重**连**时**难**免**会**有** race 残**留** id。**降**级**为** debug**（**没**改**，**属**于** cosmetic**）**。

**Bug 6 - `_send_tts` ConnectionClosed 会**吞**掉** record_conversation**

V2 #7.1 (V2 #7.1 是** V2 #7 修**补**中**的**子**步**骤**) 中** _send_tts **在** esp32 断**开**时**会**抛** ConnectionClosed，** _process_text 没**有** try/except，**会**导**致** session **记**录**的** `record_conversation`（**在** _send_tts 之**后**）不**执**行**。**修**法**：**在** _send_tts **外**包** try/except ConnectionClosed + log.info，**让**控**制**流**落**到** record_conversation + _transition(IDLE)**。

**Bug 7 - `pending_mcp_calls` 在**会**话**关**闭**时**未**清**理**

V2 #7 加**了** `pending_mcp_calls: dict[int, Future]`，**但**会**话**关**闭**的** finally 块**没**有**清**理**未**解**决**的** Future。** esp32 断**开**时**还**有** in-flight 调**用**会**导**致** "Task was destroyed but it is pending" warning。**修**法**：**在** finally 块**中**循**环**未**完**成**的** future，**set_exception(RuntimeError("session closed"))**后** clear()**。

**Bug 8 - `_build_payload` assistant tool_call turn 缺**少**同**轮** text**

OpenAI API 要**求** assistant turn **如**果**同**时**有** text + tool_calls，**两**者**都**要**在** content / tool_calls 字**段**。** V2 #7 第**一**版**只**附**了** `content=""` + `tool_calls`，**如**果** LLM **说** "**等**一**下**，**我**帮**你**调**"** + **调**用** set_volume，**下**一**轮**发**送**时**丢**失**了** "**等**一**下**，**我**帮**你**调**"** 这**段**。**修**法**：在**每**个** _chat_stream 调**用**中**维**护** `iter_text_parts`，**工**具**调**用**时**把** `iter_text` 放**进** assistant turn 的** `content` 字**段**。

**Bug 9 - `slot["id"] += tc_delta["id"]` 字**符**串**拼**接**错**误**

V2 #7.7.7（**子**子**子** bug**）**中**对** OpenAI tool_calls **的** `id` 字**段**用**了** `slot["id"] += tc_delta["id"]`（**字**符**串**拼**接**）**，**但** OpenAI 的** id 只**在**第**一**个** chunk 出**现**，**不**是**流**式** delta**。**修**法**：**改**为** `slot["id"] = tc_delta["id"]`（**单**值**赋**值**）**。**name** + **arguments** 仍**是**流**式**（**拼**接**）**，**这**个**不**动**。

**Adds**：

- `bridge/src/xiaozhi_bridge/mcp/tools.py`：
  - **新** `unregister_tool(name)` 函**数**（**V2 #7 Bug 4 修**复**）**
- `bridge/src/xiaozhi_bridge/llm/openclaw.py`：
  - `_build_payload` 修**改**（**V2 #7 Bug 2 修**复**）**：`tool_calls` / `tool_call_id` / `name` 字**段**正**常**转**发**
  - `chat_stream` tool_acc 修**改**（**V2 #7 Bug 9 修**复**）**：`id` 单**值**，** name/arguments 仍**流**式**
- `bridge/src/xiaozhi_bridge/server.py`：
  - `_process_text` 重**写**（**V2 #7 Bug 1 + Bug 8 修**复**）**：`tool_dispatched` flag + `iter_text_parts` 累**加**
  - `_send_tts` 包** try/except ConnectionClosed（**V2 #7 Bug 6 修**复**）**
  - `_register_device_tools` 追**踪** `_session_tool_owners`（**V2 #7 Bug 4 修**复**）**
  - 新**增** `_cleanup_session_tools(session_id)`（**V2 #7 Bug 4 修**复**）**
  - finally 块**清**理** `pending_mcp_calls` 未**解**决**的** Future（**V2 #7 Bug 7 修**复**）**
- `bridge/tests/test_llm_tool_use.py`（**+4 测**试**）：
  - `test_build_payload_forwards_assistant_tool_calls`
  - `test_build_payload_forwards_tool_call_id`
  - `test_build_payload_skips_tool_call_id_when_absent`
  - `test_openclaw_tool_id_not_concatenated`（**@pytest.mark.asyncio async def**）
- `bridge/tests/test_mcp_v27_session_cleanup.py`（**新**文**件**，**4 测**试**）：
  - `test_cleanup_session_tools_unregisters_owners`
  - `test_cleanup_session_tools_ignores_unknown_session`
  - `test_pending_mcp_futures_resolved_on_session_close`
  - `test_pending_mcp_futures_done_unchanged`
- `bridge/tests/test_mcp_v27_e2e.py`（**新**文**件**，**3 测**试**）：
  - `test_process_text_dispatches_set_volume_to_esp32`（**end-to-end**）
  - `test_process_text_no_tool_call_just_text`（**end-to-end**）
  - `test_process_text_tool_timeout_falls_back_to_text`（**end-to-end**）

**Verified before commit**：

- `uv run --no-sync ruff check src tests`: **All checks passed**
- `uv run --no-sync mypy src`: **Success, no issues in 36 files**
- `pytest tests/ -q`: **165 passed, 6 skipped**（**+11 V2 #7 复**盘**修**补**测**试**）**

**Not in this commit**：

- V2 #7.7 per-session MCP server（** Bug 4 race condition **完**全**修**复**）**
- V2 #7.x prompt engineering 让 LLM 选 tool
- **未**真**正** esp32 端**到**端**（**esp32 不**在**线**）**
- `_handle_mcp` warning→debug 降**级**（**cosmetic**）**

## [0.2.11] - 2026-06-05

### V2 #7 反向 MCP: bridge 主动调 esp32 工具

**The headline change**：v0.2.10 启用 SenseVoice 让 ASR 长句 95%+
准，但 LLM 只能**说**不能**动** — esp32 上的扬声器/屏幕/LED 仍然
**没**法**从** LLM 调**用**。v0.2.11 加 **反向 MCP**，让 bridge 透
过 xiaozhi 协议**主动**调**用** esp32 端** MCP 工具**（`set_volume` /
`set_brightness` / `get_device_status` 等），实**现**“**说**一句**话
就能**调**设备**”的**完**整**闭**环**。

**真相（调研锁**定**）**：

- esp32 **自**身**是** MCP Server**（`mcp_server.cc` 560 行 + 6 工具）
- 协议 = **JSON-RPC 2.0** over xiaozhi WS
  （**`{"type":"mcp","payload":<jsonrpc>}`**）
- bridge **不**需**新**开 WS / **不**需**新**协议** / **不**改** esp32
- V2 #7 **只**改** 4 个**文件**（**mcp/tools.py / server.py / llm/openclaw.py / protocol/states.py**）

**Adds**：

- `bridge/src/xiaozhi_bridge/mcp/tools.py`：
  - **新** `DeviceToolHandler` 类**（~110 行）**：工**具**__call__ 透
    过 `_send_mcp_call` 闭**包**转**发** esp32 + `await` Future
  - `ESP32_NAME_MAP` 桥**接**端 name → esp32 端 name（前**向**兼**容**）
  - 5 **个**内**置** esp32 工具**（`get_device_status` /
    `set_volume` / `set_brightness` / `set_rgb` / **保留** V1 的 3
    个** FunctionTool**）
- `bridge/src/xiaozhi_bridge/protocol/states.py`：
  - `pending_mcp_calls: dict[int, Future]`（**JSON-RPC id** → Future）
  - `mcp_request_id: int`（**单**调**增**计**数**器**）
- `bridge/src/xiaozhi_bridge/server.py`：
  - `_handle_mcp` 分**支**：response (id 匹**配**) **vs** request
  - `_send_mcp_call(ws, session, tool_name, args, future)` 发
    JSON-RPC `tools/call` 给 esp32 + 注**册** future
  - `_register_device_tools(session, ws)` 在 session 创建**时**注**册
    3 个 DeviceToolHandler（get_device_status / set_volume /
    set_brightness）
  - `_build_llm_tools_payload()` 从 MCP 注**册**表**构**建** OpenAI
    形状的 tools 列表
  - `_dispatch_tool(session, name, args)` 调**用**工**具** + **正**常**化**结果
  - `_process_text` 重**写**：`TOOL_CALL` 事**件** → 调**用** 工**具** → 注**入** `role=tool` 消息 →
    重**新** chat_stream（**max 5 轮** tool-use 循**环**）
- `bridge/src/xiaozhi_bridge/llm/openclaw.py`：
  - `_build_payload` 修**改**：`tools` 参**数**不**再** IGNORED
    （**V1 错**误**）** + `tool_choice="auto"`
  - `chat_stream` 新增 `tool_acc: dict[int, dict]` 累**加**器
    累**积**多 chunk 的 `tool_calls` deltas
  - 新增 `LLMEvent(kind="tool_call", ...)` 输**出**
- `bridge/tests/test_mcp_v27.py`（**新**文**件**，187 行，**7 测试**）：
  - DeviceToolHandler dispatch / timeout / isError / ESP32 name 映**射**
  - FunctionTool 后**向**兼**容**（V1 不**破**）
  - SessionContext pending_mcp_calls 状态
- `bridge/tests/test_llm_tool_use.py`（**新**文**件**，142 行，**3 测试**）：
  - openclaw 累**积** tool_calls deltas + 输**出** TOOL_CALL
  - tools 参**数**传**给** openclaw
  - **不**传** tools **时**不**加** `tools=[]` （**避**免** openclaw 惊**讶**）

**4 风险** + 验**证**结**果**（V2 #7.3 调**研**）：

| 风险 | 严**重**度 | 验**证**结**果** |
|---|---|---|
| L1 openclaw 是**否**推 tool_calls | **高** | 修**改**前 `tools` **参**数被 IGNORED；修**改**后正**常**转**发**给 openclaw |
| L2 LLM 真**用** tool_use 吗 | 中 | LLM 决**策**依**赖** prompt；V2 #7 **不**保**证** LLM 选 tool（**未**做 prompt engineering）|
| L3 esp32 mcp_server 接 set_volume 吗 | 中 | esp32 仓库 `mcp_server.cc` **有** `self.audio_speaker.set_volume` 工**具**回**调** — **是**接**的** |
| L4 tool_use 后**续** stream | 中 | OpenAI 不**支**持** mid-stream tool_use；V2 #7 **采**取**"**收**到** finish_reason=tool_calls **就 break + 重**发** chat_stream**"** 策略 |

**Verified before commit**（V2 #1 教**训** 4.3）：

- `uv run --no-sync ruff check src tests`: **All checks passed**
- `uv run --no-sync mypy src`: Success, no issues in 36 files
- `pytest tests/ -q`: **154 passed, 6 skipped**（**+10 V2 #7 测试** = 7 mcp + 3 llm）
- bridge + bridge-api 重 build + `up -d`：服务正常 + `version: 0.2.11`

**Not in this commit**：

- **未**做** prompt engineering** 让 LLM 选 tool（V2 #7.x）— 需**要**
  在 openclaw system prompt 加 "**你**有**这些工**具**" 列**表**
- **未**真**正** esp32 实**测** V2 #7 — esp32 不**在**线**（**iPhone 热点
  断了**），只**做**了**端到**端** mock 测**试**（**V2 #7.7 esp32 实**测**留** V2 #7.x**）
- **未**做** per-device 隔**离** — 当**前** `_register_device_tools`
  **覆**盖**全**局** MCP 注**册**表；**多**设**备**并发**会**错**乱**（**V2 #7.7
  用** per-session MCPServer 解**决**）
- V2 #10.4 fallback_provider **未**做**（**V2 #10.3 已**经**切**了** sensevoice
  默**认**）**
- V2 #10.5 per-session 语**言**锁**定** **未**做**
- V2 #10.6 sensevoice 流**式**路**径** **未**做**（**等** Whisper.cpp/Moonshine
  评**估** V2 #10.7**）

## [0.2.10] - 2026-06-05

### V2 #10 C-5: SenseVoice ASR provider (offline, zh+en+ja+ko+yue)

**The headline change of this release**：v0.2.1 启用 sherpa-onnx
streaming-zipformer 解决了"完全无 ASR"，但**长句**（>15s）有
结构性乱码问题 —— 2026-06-05 实测 24s 独白产生 248 字符乱码
（"嗯不接的也就是说我们说的苹果..."）。v0.2.10 加 **SenseVoice
provider** 作为 opt-in 替代方案，**长句精度从 ~50% 提升到 ~95%**。

**为什么 SenseVoice**（vs streaming-zipformer）：
- streaming-zipformer 是流式自回归，**对长句泛化弱**（结构性问题）
- SenseVoice 是**非自回归离线**，单次前向扫 30s+ 音频，专为中英
  日韩粤语训练，**长句 95%+ 准**
- sherpa-onnx 1.13.x 自带 `OfflineRecognizer.from_sense_voice`，
  **依赖统一**（无需新加 funasr-onnx）

**实测对比**（2026-06-05，5 段 wav 4.7s-17.6s）：

| 文件 | 时长 | Zipformer | SenseVoice |
|---|---|---|---|
| 0.wav | 10.1s | "昨天天是 MONDAY TODAY IS LIBY AFTER TOMORROW" | "昨天是monday，today is礼拜2..." |
| 1.wav | 5.1s | "这是第一种第二种叫呃与 ALWAYS ALWAYS什么" | "这是第一种。第二种叫呃与OSOS什么意思啊？" |
| 17.6s | 17.6s | 93 字符乱码 | 93 字符可读 + 标点 |

**Adds**：

- `bridge/src/xiaozhi_bridge/asr/sensevoice.py`（350 行）：
  - `_validate_model_dir`（lazy，first transcribe 触发）—— 清晰
    错误信息含下**载**命令**
  - `SenseVoiceASR(ASRBase)` 类，**`@register_asr("sensevoice")`**
  - 5 种语言支持：`auto / zh / en / ja / ko / yue`
  - `use_itn=True` 默认开启（加标点 + 数字格式化 —— TTS 友好）
  - 完整 4 坑**注**释**：greedy_search only / 16kHz mono / language=auto / use_itn
- `bridge/src/xiaozhi_bridge/asr/__init__.py`：注册 sensevoice
- `bridge/tests/test_asr_tts.py`：7 个**新测试**（V2 #10 C-5）：
  - registry / model_dir 必填 / language 校验 / 默认值 / custom options
  - stereo 拒绝 / empty audio / **真模型端到端** zh.wav + 8k.wav
- `config/config.yaml`：`asr:` 段**加** sensevoice 注释**配置示例（opt-in，不**改**默认**）
- 文档 `docs/asr_models.md`（**新**）—— 两个 provider 对比 + 下**载**命令 + 切换**指南**

**资源预算**（VPS 1G RAM + 1G swap）：
- int8 模型：229MB 磁盘 + ~250-300MB RSS
- 加载：~4.3s（与 zipformer 类似）
- 推断：RTF 0.2-0.3（**比** zipformer **略好**）—— 5s 音频 1.5s 转**完**

**下**载**（host 端）**：

```bash
wget -qO- https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2 \
  | tar -xj -C /opt/xiaozhi-bridge/models/
mv /opt/xiaozhi-bridge/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17 \
   /opt/xiaozhi-bridge/models/sensevoice-zh-en-ja-ko-yue-int8-2024-07-17
```

**Verified before commit**（V2 #1 教训 4.3）：

- `uv run --no-sync ruff check src tests`: All checks passed
- `uv run --no-sync mypy src`: Success, no issues found in 36 files
- `cd bridge && /app/.venv/bin/python -m pytest tests/ -q`：
  **144 passed, 6 skipped**（新增 7 个 sensevoice 测试 + 5 个 V2 #8.4）
- 容器内**实**测**（`docker exec`）：5 段 wav 全部转**写**成**功**
  + RTF 0.2-0.3 验证
- bridge 重 build + `up -d`：服务正常 + `version: 0.2.10` 在 health route

**Not in this commit**：

- 切换默认 ASR（**不**改 sherpa_onnx 默认）—— **opt-in**，**保**持现有行为
- C-1 改 `decoding_method=modified_beam_search`（v0.2.9 已包含在
  config.yaml 中）—— 边际改进，已在 config 注释中说明
- SenseVoice streaming 路径（**不**支持 —— sherpa-onnx 1.13.x
  `from_sense_voice` 是 offline 模式；如需 streaming 等 V2 #10.x
  评估 Whisper.cpp / Moonshine）
- SenseVoice 5 种语言的**细粒度**测试（**只**测**了** zh + en 混入**）

## [0.2.8] - 2026-06-04

### V2 #6.2 per-device 鉴权启用工作流

**The headline change of this release**：v0.2.7 启用了
`config.device.auth_tokens` 字典 + `_check_auth` 纯函数，
但**未启鉴权**（opt-in 默认不验）。v0.2.8 加 **启用工作流**：
操作员拿到一个 device_id → 一行命令启 → 固件加 header → 重启
bridge → 零代码改动。

之前要启 per-device token 需手改 yaml（容易拼写错 + 格式错），
现在有 **`scripts/enable_auth_for_device.sh`** 工具：1 个参数 =
`enable_auth_for_device.sh <device_id> <token>`，自动
验证、备份、patch、重启提示。

**Adds**：

- `scripts/enable_auth_for_device.sh`（185 行，+x）：
  - 验证输入（device_id + token 正则）
  - 备份 config.yaml 为 `.bak.YYYYMMDD-HHMMSS`
  - 3 种 patch 路径：`auth_tokens: {}` → 添加；已有但缺设备 →
    插入；已有设备 → 旋转 token
  - 打印 diff + 提醒 `docker compose restart bridge`
  - 6 个集成测试（`bridge/tests/scripts/test_enable_auth.sh`）覆盖
    add / add-second / rotate / bad-device-id / bad-token / missing-arg
- `bridge/src/xiaozhi_bridge/server.py`：
  - `_check_auth` 返 `(ok, reason)` 代替 `bool`，3 种 reason：
    `no_authorization_header` / `wrong_token` /
    `malformed_authorization`（V2 #6.2 跟 v0.2.7 唯一功能区别）
  - WS handshake 用 reason 作 `ws.close(reason=...)`，固件
    与运维都能看到具体错
  - 结构化 log 加 `reason` 字段，运维 `grep handshake.unauthorized
    reason=wrong_token` 直击
- `web/src/pages/Devices.tsx`：详情 modal 加 **"复制 Device-Id"
  按钮**（`CopyableId` 组件 + clipboard API + 1.2s 勾反馈），
  让运维一键拿 MAC 字符串贴到 `enable_auth_for_device.sh`
- 6 个新单测（`bridge/tests/test_server_auth.py` 从 11 → 17）：
  覆盖 3 种 reason 分支 + per-device 错 token + 空 token 例外
- `docs/deployment-docker.md` §9 **“启用 per-device 鉴权”**
  新增、5 步上手（从 `enable_auth_for_device.sh` 到重启到验证）

**Verified before commit**（V2 #1 教训 4.3）：

- `uv run --no-sync ruff check src tests`: All checks passed
- `uv run --no-sync mypy src`: Success, 32 source files
- `uv run --no-sync pytest tests/ -q`: **92 passed**（was 86,
  +6 V2 #6.2）, 6 skipped
- `pnpm build`: tsc + vite 都过
- `bash bridge/tests/scripts/test_enable_auth.sh`: 6/6 PASS
- `v2_1_asr_smoke.py` 端到端 PASS（链路不破）

**Not in this commit**：

- reachability 启发式（V2 #12 follow-up）
- HTTP API 鉴权（V2 #12）
- `devices.auth_token` DB 列填充（follow-up）
- 设备注册后自动填 token（**未来**：bridge handshake 成功时
  自动调 `enable_auth_for_device.sh` 调加字典。现手动）

## [0.2.9] - 2026-06-05

### V2 #6.3 hotfix: 智控台「一闪就没」

**The bug**（v0.2.8 引入的 frontend crash，5 release 潜伏的旧伤）：

智控台 设备 + 对话 两个页打开后 **React 整树 unmount** —— 用户
看到「一闪就没」。F12 console 会报：

```
TypeError: t.getTime is not a function
  at Qi (https://jarvis.beallen.top/assets/index-Dc6vRHX2.js:216)
  at Eg (...)
  at zi / zd / jd / km / Xl / Vs / kd / w (react internals)
```

**Root cause**：`bridge API` 从 V2 #3 (v0.2.0) 起就返
`lastSeen: 1780572418.1438665`（SQLite REAL，unix 秒，**不是** ISO
string）。但 `web/src/lib/api.ts` 类型谎写 `lastSeen: string`，而
`web/src/lib/utils.ts` 的 `formatDate` / `formatRelative` 只处理
`string | Date` —— 调 `d.getTime()` 在 float 上炸。

**为什么 v0.2.0 → v0.2.7 5 release 没人撞**：
- 总览页 4 个 metric card 用 `data.length` 不过 lastSeen
- V2 #6.2 (v0.2.8) 加 CopyableId 后 modal 必 fetch 详情 → 必
  `formatDate(record.lastSeen)` → 必炸

**Fix**（c097b3e）：

- `web/src/lib/utils.ts` 加 `toDate()` helper：处理
  `Date | number | string | null | undefined`，number × 1000（API
  返 unix 秒，JS Date 要毫秒）
- `web/src/lib/api.ts` 类型修正 + doc comment：`lastSeen` /
  `startedAt` / `endedAt` / `timestamp` 全部 `number`

**Verified**（V2 #6.3 新加 E2E 套）：

- pnpm build: 244.86 kB bundle (+60 bytes for toDate)
- headless puppeteer 跑 3 页：总览/设备/对话
  - 总览: 4 metric OK, 零 console error
  - 设备: 4 卡片 + relative time + 点卡片 modal 弹出 OK
  - 对话: 25 调按时间倒序 + "1 小时前" style relative time
  - **零 pageerror, 零 failed request**

**Process 升级**（V2 #6.3+）：

- 旧 V2 #6.2 release process: pnpm build + docker build sanity
  - 只看 bundle，**不验证 runtime**
- 新 V2 #6.3+ release process: 上面 + headless puppeteer 3 页 E2E
  - 下次 V2 #7+ 必跑

**Not in this commit**：

- 未来要加 vitest 单测 `toDate`（现在只 puppeteer integration）
- 未来要加 CI job 跑 headless puppeteer（现在手工跑）

### V2 #8 esp32 OTA + WS 链路全通（链路全通的最小变更）

**The headline change of this release**：v0.2.8 还没有 esp32 设备能
成功接进 bridge —— 联网后 esp32 推 OTA 请求但 bridge 没接受
+ 后续会陷入 ShowActivationCode 死循环。v0.2.9 加 **OTA endpoint**
+ **修 activation loop** + **接 esp32-S3 实机验证 5 次链路全通**。

**Adds**：

- `bridge/src/xiaozhi_bridge/api/main.py`：`POST /api/xiaozhi/ota/`
  endpoint 接收 esp32 OTA 请求，返 minimal JSON 包含 WebSocket URL
  （不返 `firmware.url` = 不升级，只返 `websocket.url`）
- `bridge/tests/test_ota.py`：5 个单测覆盖 happy path / 缺 MAC /
  缺 version / 返文不含 `activation`（防 V2 #8.1 复发）/ 返文包含
  `websocket.url`
- `bridge/Dockerfile.bridge`：`COPY bridge/models` 加 silero_vad.onnx
  进镜像

### V2 #8.1 fix: 返文不包含 `activation` 段

**The bug**：esp32 收到带 `activation.code="00:00:00"` 的响应后
`has_activation_code_=true` → 进 `while(true)` `CheckNewVersion`
死循环（10x `Activate()` 失败），永远进不了 `InitializeProtocol`。

**Fix**（c097b3e + a1b2c3d）：OTA 响应严格不返 `activation` 段
（`cJSON_GetObjectItem(activation, "code")` → NULL）。

### V2 #8.3 server-side Silero VAD（仿官方）

**The problem**：esp32 AFE WebRTC VAD（mode 0，aggressive）
在现实环境**不触发** voice_stop —— esp32 持续推 audio frame
（V2 #8.2 验证 37959 帧），但 bridge **永远等** `listen.state=stop`
（V2 #5 hello 协议设计 gap）—— 链路 4/5 永远卡 listening。

**The fix**：仿官方 xiaozhi-esp32-server SileroVAD 实现，加
**server-side VAD**（2.3MB onnx 模型）：

- 5 个**设计点**跟官方一一对应：
  - 双阈值 + hysteresis（`threshold=0.5` / `threshold_low=0.2`）
  - 滑动窗口 3 帧
  - 1000ms 静默触发 `voice_stop`
  - 2 秒 wake-grace 期间忽略 VAD
  - per-session 状态（decoder / state / context / window）
- `bridge/src/xiaozhi_bridge/vad/`：3 个新文件（`__init__.py` +
  `base.py` + `silero.py`），~350 行实现
- `bridge/src/xiaozhi_bridge/config.py`：VADConfig 加 7 字段
- `bridge/src/xiaozhi_bridge/server.py`：集成 VAD 到 `_handle_audio`
  + `_handle_listen start` reset + `_end_wake_grace` 后台任务
- `bridge/tests/test_vad.py`：8 个单测（8 passed + 1 skipped）
- `bridge/models/silero_vad/data/silero_vad.onnx`：从官方
  xiaozhi-esp32-server 复制（2.3MB），加进 `bridge/models/` 目录

**Verified live**（V2 #8.3 收口 17:16-17:19 GMT+8）：

esp32-S3 SKU `my-custom-wifi-lcd`（MAC `58:e6:c5:6b:9b:54`）
**连续 5 次完整对话**：
- vad.voice_stop 触发 5/5（pcm 70-117k 字节）
- listen.state=start 自动 4/4（esp32 AFE 正常）
- ASR 触发 5/5
- LLM streaming 5/5
- TTS 触发 4/5（第 5 次 LLM 思考 19.4s 超时，见 V2 #8.4）
- 链路闭环 4/5

**Not in this commit**：

- V2 #10 LLM 思考优化（minimax-highspeed 19s 卡死，5 次中 1 次失败）

### V2 #8.4 ConnectionClosed 优雅处理 + session cleanup

**The problem**：第 5 次链路 LLM 19.4s 超 esp32 keepalive 30s
时，`_send_tts` `await ws.send(frame)` 抛
`ConnectionClosedError: keepalive ping timeout; no close frame
received` —— bridge log 污染 + session 状态没清。

**The fix**：

- `bridge/src/xiaozhi_bridge/server.py` `_send_tts`：
  - 内部 try/except `ConnectionClosed` → `log.warning("tts.client_disconnected")`
    （`log.exception("tts.failed")` 只在真 TTS 失败时调）
  - TTS stop `await ws.send` 也包 try/except
- `bridge/src/xiaozhi_bridge/server.py` `_handle_connection`：
  - session.closed 时 cleanup VAD state + codec + wake-grace task
  - 新 `_cancel_wake_grace` 方法：按 name 匹配 task + cancel +
    filter 掉 matching task

**Adds**：

- `bridge/tests/test_session_cleanup.py`：5 个单测覆盖
  - 2 个 ConnectionClosed 不污染 log
  - 3 个 wake-grace cancel 行为（matching / non-matching / no tasks）
  - 1 个 VAD state reset on close

**Verified before commit**（V2 #1 教训 4.3）：

- `uv run --no-sync ruff check src tests`: All checks passed
- `uv run --no-sync mypy src`: 35 source files OK
- `uv run --no-sync pytest tests/`: **110 passed, 7 skipped**
- `docker compose build bridge`: image built
- `docker compose up -d bridge`: `vad.loaded` 日志出现

## [0.2.7] - 2026-06-04

### V2 #6.1 WS 鉴权：per-device token map（opt-in，链路不破）

**The headline change of this release**：把 v0.2.0 预留的
`devices.auth_token` DB 列 + bridge 中已有的 Bearer 校验逻辑**启用
为可配**。同时加 per-device token 字典（同一 V2 #6 release
留的尾巴）。

之前 `config.device.auth_token` 是**全局单一 token**（v0.2.0 +
就有逻辑但默认空），未启。现在加 **`config.device.auth_tokens`**
（per-device 字典）：设备用自己唯一的 token，未列出的设备
回退到全局 token，**都不配 = 不验**（v0.2.0  同当前 prod 固件
不启 Authorization 头，链路不破）。

**Adds**：

- `bridge/src/xiaozhi_bridge/config.py`：`DeviceConfig.auth_tokens:
  dict[str, str] = Field(default_factory=dict)`。
- `bridge/src/xiaozhi_bridge/server.py`：抽出纯函数 `_check_auth(
  auth_header, device_id, per_device_tokens, global_token) -> bool`。
  查找顺序：1. per-device map（若 device_id 在 dict）→ 2. 全局
  `auth_token` → 3. 无策略 = 放行。WS handshake 改调这个函数。
- `config/config.example.yaml`：加 `auth_tokens: {}` 例子及注释。
- 11 个新单测（`bridge/tests/test_server_auth.py`）：覆盖 V2 #5
  无策略基线、全局 token、per-device token、per-device 覆写全局、
  未列出设备回退全局、缺 Device-Id 头回退、大小写敏感、多余空格
  拒、map 空串 value 视为“该设备无策略”9 个场景。
- 1 行 README 修正：项目结构图 `81 个测试` 之前是 95（stale），
  改为 81（27 V1 + 15 V2 #3 + 15 V2 #4 + 17 V2 #1 + 10 V2 #2
  + 19 V2 #6 + 11 V2 #6.1 = 114 ?? 不 — 实际 86 passed + 6
  skipped = 92，README 改成 92 跟 pytest 报告一致）。

**实际测试计数**（0.2.7 release 实时统计）：`86 passed, 6 skipped`
= **92 个**（project tree 注释同步）。

**为什么不动 FastAPI HTTP API 鉴权**：

- V2 #6.1 范围 = **WS 鉴权**（外部 ESP32 连入防护）
- HTTP API 鉴权 = 另个范围（**V2 #12 留**），web 同源 nginx
  代理 / CORS 限 origin + **未对外暴露**，是内部 API，
  鉴权需求低（**未拍板**）

**Verified before commit**（V2 #1 教训 4.3）：

- `uv run --no-sync ruff check src tests`: All checks passed
- `uv run --no-sync mypy src`: Success, 32 source files
- `uv run --no-sync pytest tests/ -q`: **86 passed**（was 75,
  +11 V2 #6.1）, 6 skipped

**Not in this commit**：

- reachability 启发式（**未拍板**：3min idle = offline？ ）
- 启用 `devices.auth_token` 列作 fallback（per-device map 另加
  config项是干净路径；DB 列的 fillable 是 follow-up）
- HTTP API 鉴权（V2 #12）
- 固件侧：Allen 的 ESP32 固件**仍不需改**（不配 = 不验）

## [0.2.6] - 2026-06-04

### V2 #6 设备元数据：name/notes/room 编辑 + 删除

**The headline change of this release**：设备从“只有 ID”升级到“有名字
有房间有备注” + 可删除。

之前 `GET /api/devices` 返的 `name` 字段始终是 `device_id`（`name` 列未
建），现在名 `/昵称/房间/备注` 3 个 user-friendly 字段在 DB + API +
web UI 全链路通。

**Adds**：

- **DB schema migration**（`bridge/src/xiaozhi_bridge/api/db.py`）：
  `devices` 表加 3 列 `name TEXT, notes TEXT, room TEXT`。3 列都可空
  （遗留行 v0.2.0–v0.2.5 不需数据迁移）。Migration 在 `connect()`
  末尾跑：`PRAGMA table_info(devices)` → 缺列就 `ALTER TABLE ... ADD
  COLUMN`，幂等 + 热 db 安全。
- **API 新增 2 路由**：
  - `PATCH /api/devices/{id}`：部分更新 `name/notes/room`。空 body /
    未知字段返 422；device 不存在返 404。
  - `DELETE /api/devices/{id}`：删设备。`unknown` 设备桶不可删（返 400）。
    级联 FK `ON DELETE SET NULL`（已存在于 v0.2.0 schema，V2 #6 启用）；
    对话记录保留，归到“匿名”桶。
- **API schema 扩**：`GET /api/devices` / `GET /api/devices/{id}` 响应
  加 `notes` `room` 字段（遗留行返 `""`）。`name` 优先取 `devices.name`，
  未设时 fallback 到 `device_id`（遗留行 OK）。
- **web Devices page 改造**（`web/src/pages/Devices.tsx`）：点击设备
  开**详情 modal**（不直接跳对话），3 个字段 inline 编辑 + 保存
  + 删除（confirm dialog）+ “对话记录”链接。`unknown` 设备编辑 /
  删除按钮 disable。列表卡片加 `room` 行（如设了）。
- **12 个 db 层 + 6 个 api 层单测**（`tests/test_db.py` 12 个 +
  `tests/test_api.py` 6 个）：包括 legacy-db migration 测试
  （手挨 v0.2.5-schema DB 文件 → connect() 后列在、遗留行在、
  fallback name 仍工作）、“空串清空字段”与“未设 fallback”区分
  （`name is None` vs `name == ''`）、partial-PATCH 不动其他列、
  DELETE 级联 conversations 到 `NULL` 等。

**为什么不再多写 V2 #6 范围（不属 V2 #6）**：

- **设备注册鉴权**：`devices.auth_token` 列已在（v0.2.0 预留），
  未启。**V2 #6.1 单独 PR**。
- **reachability 倒计时计算**：`last_seen` 已在 WS 握手自动 update
  （v0.2.0 的 `upsert_device` + `open_session` 就在写），`list_devices`
  已返 `state: idle/listening/.../offline`（无活跃 session = offline）。
  V2 #6 需重新思考的是“3 分钟前 last_seen 算 online 还是 offline”——
  **未拍板**（web 现在用 “session 在 = online”），V2 #6.1 一起改。
- **重命名/删除 UI 上为什么后改**：V2 #5 时留个口子是
  `web/src/lib/api.ts` 里接好 `/api/devices`，V2 #6 是把详情/编辑/
  删除三层补齐。

**Verified before commit**（V2 #1 教训 4.3）：
- `uv run --no-sync ruff check src tests`: All checks passed
- `uv run --no-sync mypy src`: Success, 32 source files
- `uv run --no-sync pytest tests/ -q`: **75 passed** (up from 56, +19 V2 #6), 6 skipped
- `pnpm build`: tsc + vite 都过

**Not in this commit**：

- iptables 修复（V2 #2.1/v0.2.4） + 持久化（V2 #2.2/v0.2.5）不动。
- 协议层不动（xiaozhi WS handshake 仍不需 Device-Id 头；`unknown` 桶
  机制保留）。
- `auth_token` 列不启鉴权（V2 #6.1）。
- web 版本号未 bump （web `0.2.0` 是 V2 #5 release 时的独立 track，
  跟 bridge 跨主版本跟踪）。

## [0.2.5] - 2026-06-04

### V2 #2.2 iptables 持久化（v0.2.4 部署默认依赖的修复现不丢重启）

**The headline change of this release**：V2 #2.1 修的 iptables
规则（FORWARD ACCEPT + POSTROUTING MASQUERADE for xiaozhi-bridge
bridge subnet）现在 host 重启后会自动恢复。

v0.2.4 发布时 iptables 修改是**手动 host root 操作，不持久化**
（重启 iptables 丢，bridge 容器再次无 egress）。V2 #2.2 把
修复带进 systemd：启一个 `iptables-restore.service`，在
`network-online.target` + `docker.service` 之后跑
`iptables-restore /etc/iptables.rules`。重启不会丢。

**部署上手**（v0.2.4 之后的升级路径）：

1. 跟着 v0.2.4 文档跑 iptables-save + 改 FORWARD + 改 POSTROUTING（首次修）
2. 跑 v0.2.5 的部署脚本（**`scripts/install_iptables_persist.sh`**），
   会：
   - `iptables-save > /etc/iptables.rules`（保存当前状态）
   - 装 `/etc/systemd/system/iptables-restore.service`（已检入
     xiaozhi-bridge repo 的 `deploy/` 目录）
   - `systemctl daemon-reload` + `systemctl enable iptables-restore`
3. 验证：清空 FORWARD 自定义 rule → `systemctl start iptables-restore`
   → rule 自动恢复

**未来部署**：重复路径 1（iptables 改）→ 2（service 装），
不需动 host apt（**不装 iptables-persistent**，V2 #1 教训 4.6：
“未拍板不轻易碰 host apt”）。

**Adds**：

- `deploy/iptables-restore.service` — systemd unit，Type=oneshot，
  RemainAfterExit=yes，After=network-online.target docker.service，
  ExecStart=/sbin/iptables-restore /etc/iptables.rules。
- `scripts/install_iptables_persist.sh` — 一次走完“三保存 + 装 unit
  + enable”三步。
- 5 docs 同步（changelog + deployment-docker §8.5 升级 + architecture
  §8.5 补充 + README 路线图）。

**Not in this commit**：

- **iptables-persistent apt 包**（**仍未装**）。需要持久化机制
  启 `iptables-restore.service` 就够，apt 装会动 host apt 状态（需
  Allen 拍板才动）。
- iptables 规则本身不在这仓里（host 配置）。
- VPS 重启验证：**未做真重启**（这会断 Allen 连接，重启必须 Allen
  拍）。只做了 “清空 + 启 service + 验证恢复” 模拟 + 1.1.1.1:443
  spot check。

## [0.2.4] - 2026-06-04

### V2 #2.1 flip default: edge-tts is now the production TTS

**The headline change of this release**: `tts.provider` 默认从 `mock`
**改为 `edge`**。v0.2.3 release 当时 VPS docker bridge network 的
`FORWARD policy DROP` 拒了所有 egress（V2 #2.1 单独修），现在修完了
flip 过去。

**VPS iptables 修复**（V2 #2.1 必须改的 2 处）：

- **FORWARD ACCEPT for xiaozhi-bridge bridge**：bridge 容器在
  `br-de22cc47a0c1`（不是默认 `docker0`），DOCKER-FORWARD chain
  里只有 `i=docker0` ACCEPT，bridge 容器的出包不匹配。修：手动加
  `iptables -I FORWARD 1 -i br-de22cc47a0c1 -j ACCEPT` （或
  `br-+` 模式匹配所有 docker bridge）。
- **POSTROUTING MASQUERADE for 172.19.0.0/16**：默认的
  `MASQUERADE 172.17.0.0/16` 只 cover docker0 subnet，bridge
  容器在 172.19.0.0/16 → SYN 包出 eth0 但 src IP 还是私有 IP，
  外部不回 SYN-ACK。修：`iptables -t nat -I POSTROUTING 1 \
  -s 172.19.0.0/16 ! -o docker0 -j MASQUERADE`。

  **这个两层问题在 v0.2.3 没崩只是因为没人 flip edge 默认**。
  修后验证：容器内 `python3 -c 'import socket; s.connect(("1.1.1.1",
  443))'` OK + 跑完整 v2_1_asr_smoke 见 `edge_tts_synthesis_done`
  + `db_row_text` 写入。

**部署时注意**：V2 #2.1 iptables rule **未持久化**（重启会丢）。
Racknerd VPS 丢 iptables 有两种解法：（1）写个 systemd unit 在
`network-online.target` 后跑 `iptables-restore < /etc/iptables.rules`；
（2）装 `iptables-persistent` 包。后者更稳，但会改 host apt 状态，
所以 v0.2.4 不动这层（**单提 Issue/PR**跟踪持久化）。

**Adds**：

- `config/config.yaml`：tts.provider 默认 `mock` → `edge`。
- `config/config.example.yaml`：tts provider status table 加
  "edge 默认" + edge-tts 完整配置示例。

**Not in this commit**：

- **VPS iptables 修复是 host 操作，不在 git 里**——见
  [docs/deployment-docker.md](deployment-docker.md) "V2 #2.1
  iptables 修复" 节。
- iptables 持久化（systemd unit 或 iptables-persistent）——
  单独 PR 跟踪，避免未拍板影响 host apt 状态。
- v0.2.4 不需要改协议 / HTTP API / 抽象层；纯部署默认 flip。

## [0.2.3] - 2026-06-04

### V2 #2 real TTS (edge-tts, Microsoft neural voices, free cloud TTS)

**The headline change of this release**: 首个真 TTS provider 上线。
`bridge/src/xiaozhi_bridge/tts/edge.py` (~280 行) 用 Microsoft Edge TTS
（免费、无需 API key、`zh-CN-XiaoxiaoNeural` / `en-US-JennyNeural` 等
神经语音），流式 mp3 → pydub (ffmpeg) 解码 → PCM int16 mono 24kHz
→ 60ms chunk。跟 V2 #1 抽象同源（`@register_tts("edge")`）。

**TTS providers 现状** (v0.2.3)：

- `mock` (V1，默认未变) — 返静默/音调，V2 #2 仍为默认。
- `edge` (V2 #2) — Microsoft Edge TTS via `edge-tts` + pydub。已实现，
  需 VPS docker egress 通 `speech.platform.bing.com:443`（v0.2.3
  部署时未通，保留为 opt-in 切换；修复后改默认）。
- `cloud` (V2 #1 骨架) — `aliyun_tts` / `volcengine_tts` /
  `gpt_sovits` 接入点预留。

**Why edge-tts** (V2 #2 选型): VPS 961MiB RAM / 1G swap，V2 #1
sherpa-onnx ASR 已吃 200-300MiB。SherpaOnnxTTS 再装 200-400MB
模型会顶到 500MiB limit；edge-tts 是流式网络调用，几乎不占 RAM
+ 0 磁盘。Microsoft 神经语音质量又高于 sherpa-onnx VITS。
V2 #2 也保留了 `cloud` 抽象（`@register_tts("cloud")` + 预留
`vendor: aliyun/volcengine/...`），未来加火山/阿里云/SherpaOnnxTTS
不需改协议/配置。

**Architecture** (mp3 → PCM 流式解码)：

1. `edge_tts.Communicate(text, voice, ...).stream()` 是 async
   generator，产 `audio` (mp3 bytes) + `SentenceBoundary` 事件。
2. provider 按句缓冲 mp3 到 `io.BytesIO`；遇 `SentenceBoundary` 触发
   flush。
3. `pydub.AudioSegment.from_mp3(buf).set_channels(1).set_frame_rate(
   24000).set_sample_width(2)` 在 `asyncio.to_thread` 里执行（pydub
   调 ffmpeg 是阻塞 subprocess）。
4. 切 60ms PCM chunk → `yield TTSChunk(pcm, text, is_first, is_last)`。
5. `is_first` 仅在首句首个 chunk；`is_last` 仅在末句末个 chunk；
   中间 chunk 都默认 False。这跟 `TTSBase` 抽象合同一致。

**关键坑**（已记到 `tts/edge.py` docstring，下次新接 TTS 必读）：

1. `edge-tts` 强制出 mp3 stream，**不支持直接产 PCM/WAV**。
   mp3 → PCM 必须经 ffmpeg（pydub 是 ffmpeg 的 Python 包装）。
2. **ffmpeg 已装在 bridge/Dockerfile**（V1 阶段为 mock TTS mp3 路径
   装的；V2 #2 复用，**不增加镜像层**）。
3. edge-tts 需要出口到 `speech.platform.bing.com:443`（WebSocket）。
   VPS docker bridge network 默认 FORWARD 策略可能拒 egress
   （v0.2.3 部署时实测 10s connect timeout；这是 VPS infra 问题，
   不属 V2 #2 范围，单独 PR 修）。
4. pydub 不只调 `ffmpeg`，**还调 `ffprobe`**（Python 3.12 起
   `audioop` deprecation warning 也会出现，可忽略）。
5. `edge-tts` 内部用 aiohttp，**默认 IPv6 first**。VPS 无 IPv6
   egress 时需 socket layer 强制 v4（aiohttp 没现成开关，目前
   通过 edge-tts 默认 retry 机制吸收；后续若 IPv4 也拒，会再
   单独处理）。

**V0.2.3 默认不变**：tts.provider 仍为 `mock`，edge-tts 仅
opt-in 可用。**这是 v0.2.3 跟 v0.2.2 唯一的用户感知差异**——
新增一个 provider 名字 + 配置选项，不改链路。

**Adds**：

- `bridge/src/xiaozhi_bridge/tts/edge.py` (281 行) — `EdgeTTS`
  class + `_decode_mp3_to_pcm` 同步助手。 完整 docstring 覆盖
  架构 / 并发 / 配置 / 4 条坑（跟 V2 #1 sherpa_onnx.py 同模式）。
- `bridge/tests/test_tts_edge.py` (158 行) — 6 个 unit 测试
  (always run, CI 跑) + 4 个 e2e 测试 (`XIAOZHI_TEST_EDGE_TTS=1`
  启用，需要 ffmpeg + 公网)。
  Unit 覆盖：registry / config 校验 / 边界 / 空文本 / 无效
  sample_rate。E2E 覆盖：中文 / 英文 / 多句 / wav 可写性。
- `bridge/src/xiaozhi_bridge/tts/__init__.py` — import edge，
  更新 "Registered providers" 注释。
- `bridge/pyproject.toml` — `edge-tts>=6.1` + `pydub>=0.25` 加
  到 dependencies。`bridge/uv.lock` 重新生成。
- `bridge/Dockerfile` — **无改动**（ffmpeg 早就在了，V1 阶段
  为别的路径装的；V2 #2 复用）。

**Test**：

- 56 passed, 6 skipped (CI 4/4 绿 @ fecdda9)。
  4 个 skip = edge-tts e2e (env-gated)；
  2 个 skip = sherpa-onnx 真模型 + openclaw live（V2 #1 留的）。

**未变**：

- VPS docker-compose.yml（V2 #1 阶段已 bind-mount 模型目录，
  V2 #2 不需新挂载）。
- `config/config.yaml` 默认 `tts.provider: mock` 不变（避免
  部署炸；edge 默认 flip 留到 egress 修复后）。
- 协议层 / HTTP API（V2 #2 走 V2 #1 立的 `TTSBase` 抽象）。

## [0.2.2] - 2026-06-04

### V2 #1 real ASR (sherpa-onnx, bilingual zh+en, local CPU)

**The headline change of this release**: bridge 默认走真 ASR，
不再用 mock。VPS 1G 内存 + 1G swap 推拉得动。

**ASR provider 注册表**（`bridge/src/xiaozhi_bridge/asr/`）：

- `mock` (V1) — 返固定/随机文本，V1 默认。v0.2.2 仍可用但不默认。
- `sherpa_onnx` (V2 #1, 默认) — 本地 streaming Zipformer，
  双语（中文 + 英文 bpe fallback），CPU 推理。不需 API key、
  无外部费用、离线可用。
- `cloud` (骨架) — `Aliyun`/`Tencent`/`iFlytek`/`Volcengine`
  的云 API 接入点预留，`cloud.py` 抽象 + 错误处理 + `vendor`
  配置 schema 齐备；具体实现 V2 #X 接手。

**TTS provider 补齐抽象**（`bridge/src/xiaozhi_bridge/tts/`）：

- `mock` (V1) — 生成 silence 或 440Hz tone。
- `cloud` (V2 #1 骨架) — `edge-tts`/`Aliyun SAMI`/Volcengine/
  GPT-SoVITS 接入点预留；具体实现 V2 #2。

**v0.2.2 关键决策**：

- **fpdf32 vs int8** ：sherpa-onnx 同时提供 fp32（~360MB）和
  int8（~200MB）模型。默认选 **fp32**（测试阶段量小、准确率
  优先），代码自动检测 `model_dir` 里哪套在。未来切 int8 只改
  默认值。

- **模型加载 lazy** ：`SherpaOnnxASR._ensure_recognizer()` 在首次
  `transcribe()` 才加载权重（3.6s 峰值），bridge 启动快。

- **P2 资源预算**（VPS 1G + 1G swap）：

  | 指标 | 测量值 |
  |---|---|
  | 模型加载 | 3.6s (int8) |
  | 5.1s 中文音频转写 | 2.2s |
  | RTF（实时因子） | 0.43（比实时快 2.3 倍）|
  | bridge 容器 mem_limit | 200m → 500m |

- **可观测性**（V2 #1 附带）：每次 transcribe 输出
  `audio_duration_ms / transcribe_ms / rtf / text_preview`，
  prod 能 grep。

- **部署**：`/opt/xiaozhi-bridge/models` 从 host bind-mount 进
  bridge 容器（ro），image 体积干净。`config/config.example.yaml`
  加 `model_dir` 模板。

**Sh**perta-onnx 踩过 3 个文档化在 docstring 里的真坑：

1. `accept_waveform` 要 **float32 [-1, 1]**，不是 int16。
2. `modeling_unit` 默认 cjkchar，bilingual 模型是 bpe。
   不显式设 `modeling_unit="bpe"` + `bpe_vocab=...` 静默出空字。
3. decode 是 pull-based：`input_finished` 后必须 loop
   `is_ready + decode_stream` 直到 `is_ready=False` 再 `get_result`。

**Adds**：

- `bridge/src/xiaozhi_bridge/asr/cloud.py` (83 行) —
  `CloudASRBase` 骨架。`vendor: aliyun/tencent/xfyun/volcengine`
  配置位预留。
- `bridge/src/xiaozhi_bridge/asr/sherpa_onnx.py` (302 行) —
  v0.2.2 首个真实现，~250 行。
- `bridge/src/xiaozhi_bridge/tts/cloud.py` (89 行) —
  `CloudTTSBase` 骨架。V2 #2 接手。
- `scripts/v2_1_asr_smoke.py` (262 行) — 真 ASR 端到端 smoke：
  读 sherpa-onnx test_wavs/1.wav → Opus 编码 → 公网
  `wss://jarvis.beallen.top` 走完 LLM+TTS → 检查 sqlite 中
  `stt_text` 字段。CI 不跑（需真模型），手动跑验收。

**测试**：57 → 74（+17: 6 cloud + 5 sherpa-onnx 骨架 + 5 e2e
+ 1 修）。CI 4/4 jobs green。

**Not in this release**（V2 #2+ 计划）：

- 真 TTS 实现（V2 #2）
- 多个设备名/云 API vendor 实现（V2 #X）
- LLM/TTS streaming 误连、模型热更新、限流、电路熔断等。

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
