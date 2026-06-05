# 模块拆分规划 (V2 #11 / v0.2.13)

> **目的**：把 `server.py` 1124 行主类的"业务流水线"代码剥离到独立模块，
> 后期维护 / 修改时只动对应模块，不动连接生命周期和协议层。
>
> **不**改**架构**，**只**做"内部代码搬家"**——** WS 协议 / 消息 schema / 状态机
> / 设备注册表 / DB schema / 现有 API **全**保**持**不**变**。**

---

## 1. 现状审计

### 1.0 参考项目（官方 server `78/xiaozhi-esp32-server`）的架构借鉴

**官方**（30K+ 行的 Python 项目）的模块划分策略（核心是按职责拆文件）：

| 官方模块 | 行数 | 我们对应 | 我们状态 |
|---|---|---|---|
| `core/connection.py` ConnectionHandler | **1661** | `server.py` XiaozhiBridgeServer | 🔴 我们 1124，**也**大**，**但**比**官**方**还**小** 30%** |
| `core/handle/textMessageHandlerRegistry.py` | 47 | ❌ 无 | **❌ 我**们**没**有**（**match-case in _main_loop**）** |
| `core/handle/textMessageProcessor.py` | 44 | ❌ 无 | **❌ 我**们**没**有** |
| `core/handle/textHandler/abortMessageHandler.py` | 16 | server.py _handle_abort (9 行) | 🟡 **我**们** 9 行**没**必**要**单**独**文**件** |
| `core/handle/textHandler/helloMessageHandler.py` | 18 | server.py _handle_connection (含 hello 段 30 行) | 🟡 **拆**出**来**更**清**晰** |
| `core/handle/textHandler/listenMessageHandler.py` | 99 | server.py _handle_listen (41 行) | 🟡 **拆**出**来**更**清**晰** |
| `core/handle/textHandler/mcpMessageHandler.py` | 21 | server.py _handle_mcp (53 行) | 🟡 **拆**出**来**更**清**晰** |
| `core/handle/textHandler/serverMessageHandler.py` | 91 | (我们**没**有** server→device 业务**消**息**)** | n/a |
| `core/handle/textHandler/iotMessageHandler.py` | 21 | (我们**没**有** IoT 业务**消**息**)** | n/a |
| `core/handle/textHandler/pingMessageHandler.py` | 45 | (我们**没**有** ping 协议**)** | n/a |
| `core/providers/tools/base.py` ToolType + ToolExecutor | 8 + 30 | ❌ 无 | **❌ 我**们**没**有**（**mcp/tools.py 是**全**局** dict**）** |
| `core/providers/tools/unified_tool_manager.py` ToolManager | 200+ | ❌ 无 | **❌ 我**们**没**有** |
| `core/providers/tools/unified_tool_handler.py` UnifiedToolHandler | 242 | ❌ 无 | **❌ 我**们**没**有** |
| `core/providers/tools/device_mcp/mcp_handler.py` MCPClient | **403** | mcp/tools.py (307) | 🟡 **我**们**的**设**计**已**有** ESP32_NAME_MAP + pending_mcp_calls，**但**没**有** async Lock** |
| `core/providers/tools/device_mcp/mcp_executor.py` DeviceMCPExecutor | ~80 | ❌ 无 | **❌ 我**们**没**有**（**DeviceToolHandler.__call__ 直**接**发** JSON-RPC**）** |
| `core/providers/asr/` 17 个** provider | ~3000 | `asr/` 5 个** provider | 官**方**比**我**们**多** 12 个**（**Doubao / Xunfei / Vosk / OpenAI / ...**）** |
| `core/providers/tts/` 22 个** provider | ~5000 | `tts/` 4 个** provider | 官**方**比**我**们**多** 18 个**（**Aliyun / Volcengine / GPT-SoVITS / FishSpeech / ...**）** |

**官**方**的**核**心**设**计**思**想**（**值**得**借**鉴**）**：

1. **每**个**消**息**类**型**有**单**独**的** `XxxTextMessageHandler` 类**（**最**多** 100 行**）**。**注**册**表** + 派**发**器**把** `_main_loop` 替**换**为** `await message_processor.process_message(conn, message)`**（**3 行**）**。
2. **ToolType 抽**象**（**Enum**）** + **ToolExecutor 抽**象**（**protocol**）** + **ToolManager 派**发**。**每**种**工**具**类**型**（**server / device_iot / device_mcp / mcp_endpoint**）**有**自**己**的** Executor**。**添**加**新**类**型**只**添** Executor** + register_executor**。
3. **MCPClient 是** per-session 的**（**带** asyncio.Lock**）**，**持**有** tools / name_mapping / call_results / next_id / ready**。**这**是** V2 #7.7 per-session MCP server 的**完**整**蓝**图**。
4. **ConnectionHandler 持**有** `mcp_client`**（**per-session**）**。**不**是**全**局** dict**。

**官**方**有**的**我**们**没**有**的** 5 个**核**心**架**构**（**对**应**的**我**们**的**缺**失**）**：

| # | 官**方** | 我**们**当**前** | 缺**失**严**重**度** |
|---|---|---|---|
| 1 | `textMessageHandlerRegistry`（注**册**表**）| `match-case` in `_main_loop` | **🟡 中**（**加**新**消**息**类**型**要**改** server.py**）** |
| 2 | `textMessageProcessor`（**派**发**）| `_main_loop` **直**接**调** handler** | 🟢 低（**同**上**）** |
| 3 | `textHandler/*.py`（**按**消**息**类**型**拆**）| 全**塞** server.py | **🟡 中**（** V2 #7.7 加** mcp** 复**杂**度**爆**炸**）** |
| 4 | `ToolType` + `ToolExecutor` + `ToolManager` | 全**局** dict `_REGISTRY` | **🔴 高**（**Bug 4 race condition 的**根**源**）** |
| 5 | `MCPClient` per-session 带** asyncio.Lock | `session.pending_mcp_calls` dict | **🔴 高**（**V2 #7.7 必**要**）** |

### 1.1 代码量分布（5798 行 Python）

| 模块 | 文件 | 行 | 状态 |
|---|---|---|---|
| `server.py` | 1 | **1124** | 🔴 **业务流水线塞进主类** |
| `api/db.py` | 1 | 601 | 🟢 DB CRUD（合理）|
| `api/main.py` | 1 | 424 | 🟢 HTTP API 路由（合理）|
| `mcp/tools.py` | 1 | 307 | 🟡 **官**方**是** 4 文件**（**base + manager + handler + executor**）** |
| `asr/*` | 5 | 1064 | 🟢 provider 抽象+4 实现（**官**方** 17 provider 详**细**但**架**构**一**致**）** |
| `llm/*` | 3 | 474 | 🟢 client 抽象+openclaw+prompts（合理）|
| `tts/*` | 4 | 509 | 🟢 provider 抽象+3 实现（合理）|
| `vad/*` | 2 | 313 | 🟢 provider 抽象+silero（合理）|
| `mcp/server.py` | 1 | 172 | 🟢 MCP 协议路由（合理）|
| `protocol/*` | 3 | 468 | 🟢 协议层（合理）|
| `config.py` | 1 | 243 | 🟢 pydantic-settings（合理）|
| `main.py` | 1 | 104 | 🟢 入口（合理）|

**结论**：**12 个子模块都分得清楚**，**唯独** `server.py` **1 个文件塞了 1124 行**，
是典型的"主类长期演化"问题。

### 1.2 server.py 13 个方法的职责分布

| 方法 | 行 | 调用下游 | 真实职责 | 归类 |
|---|---|---|---|---|
| `__init__` | 65 | - | 拼装 server 内部状态 | lifecycle |
| `start` | 40 | - | 启动 WS + HTTP | lifecycle |
| `stop` / `serve_forever` | 9+13 | - | 启停 | lifecycle |
| `_handle_connection` | 143 | - | WS 握手 + lifecycle + finally | **lifecycle** |
| `_main_loop` | 30 | - | 消息路由（match-case）| **lifecycle → 应**该**替**换**为**注**册**表**派**发**）** |
| `_handle_audio` | 66 | self.vad / self._codecs | VAD + Opus 解码 + 缓冲区 | **bridge→audio** |
| `_handle_listen` | 41 | self.vad / self.asr | listen 状态机 + 触发 ASR | **bridge→audio** |
| `_handle_abort` | 9 | - | 中断 | lifecycle |
| `_handle_mcp` | 53 | self.mcp / self.sessions | MCP 协议路由 | **lifecycle（薄）** |
| `_send_mcp_call` | 32 | ws + sessions | 发 JSON-RPC 给 esp32 | **mcp module** |
| `_register_device_tools` | 69 | self.mcp + 闭包 | session 创建时注册 esp32 tools | **mcp module** |
| `_cleanup_session_tools` | 26 | self.mcp | session 关闭时解绑 | **mcp module** |
| `_build_llm_tools_payload` | 21 | self.mcp | MCP → OpenAI shape | **mcp module** |
| `_dispatch_tool` | 30 | self.mcp | 调工具 + 异常归一化 | **mcp module** |
| `_process_turn` | 43 | self.asr / self._process_text | ASR → text | **pipeline** |
| `_process_text` | 158 | self.llm / self.mcp / self._send_tts | **LLM tool-use 循环** | **pipeline（核心）** |
| `_send_tts` | 86 | self.tts | TTS 串流 | **pipeline** |
| `_transition` | 10 | self._db | 状态机 + DB | **protocol** |
| `_end_wake_grace` / `_cancel_wake_grace` | 13+22 | session | VAD grace task | **vad module** |

**核心问题**：`_process_text`（158 行，**含 LLM tool-use 循环**）+ `_send_tts`（86 行，**含 TTS 协议**）+ `_handle_audio`（66 行，**含 VAD+Opus**）+ 5 个 mcp-related 方法（~200 行）+ 4 个 message handler（~100 行）= **~600 行业务代码塞在 server.py**，**真正属于连接生命周期的只有 ~250 行**。

---

## 2. 拆分原则（**5 条不变量**）

1. **协议不变量** —— xiaozhi WS 消息 schema、MCP JSON-RPC、xiaozhi 状态机
   **1 字节都不改**。下游设备固件 0 适配。
2. **DB 不变量** —— `bridge.db` schema（devices / sessions / conversations）
   **不**加**列**、**不**改**类**型**。已部署的 VPS **不**需**要**迁**移**。
3. **配置不变量** —— `config.yaml` schema 0 改。已部署的 VPS
   **不**需**要**改**配**置**。
4. **API 不变量** —— `bridge-api` HTTP 端点 0 改。智控台 0 适配。
5. **依赖不变量** —— `pyproject.toml` 0 改。**只**搬**家**，**不**引**新**依**赖**。

**简**而**言**之**：**内**部** refactor**，**外**部** 0 变**化**。

---

## 3. 拆分规划（**学**习**官**方** + 8 个**新**文**件**）**

**重**要**改**动**：**借**鉴**官**方** `78/xiaozhi-esp32-server` 的**模**块**划**分**，**从**原**来**的** "4 个**新**模**块**"** 升**级**为** "**8 个**新**文**件**（6 个**新**模**块** + 2 个**架**构**重**构**）**"。**核**心**思**想**：
1. **每**个**消**息**类**型**有**单**独**的** handler**（**学**官**方** textHandler/*.py**）**
2. **ToolType 抽**象**（**学**官**方** base.ToolType**）** + ToolExecutor 抽**象** + ToolManager 派**发**（**解**决** Bug 4 race condition**）**
3. **MCPClient per-session**（**学**官**方** mcp_handler.py MCPClient**）** —— V2 #7.7 的**完**整**蓝**图**

### 3.1 `mcp/handlers.py`（**新**）

**目标**：把 server.py 里 5 个 mcp-related 方法抽到独立模块，作为薄 DeviceMCPExecutor（学官方模式）。

| 来源（server.py）| 行 | 抽到 handlers.py |
|---|---|---|
| `_send_mcp_call` | 32 | `DeviceMCPExecutor.send_call(ws, session, tool_name, arguments, future)` |
| `_register_device_tools` | 69 | `DeviceMCPExecutor.register_tools(client, conn, session, ws)` |
| `_cleanup_session_tools` | 26 | `DeviceMCPExecutor.cleanup(client, session_id)` |
| `_build_llm_tools_payload` | 21 | `DeviceMCPExecutor.build_tools_payload(client)` |
| `_dispatch_tool` | 30 | `DeviceMCPExecutor.dispatch(client, session, name, args)` |

**结构**：
```python
# bridge/src/xiaozhi_bridge/mcp/handlers.py
class DeviceMCPExecutor:
    """V2 #7.7: bridge→esp32 MCP request/response orchestration.

    One of multiple ToolExecutors (Device / Function / Server / IoT).
    Holds no per-instance state — all per-session state lives in
    the per-session MCPClient (mcp/client.py).
    """
    tool_type = ToolType.DEVICE

    async def send_call(...) -> None: ...
    def register_tools(client, conn, session, ws) -> None: ...
    def cleanup(client, session_id) -> None: ...
    def build_tools_payload(client) -> list[dict]: ...
    async def dispatch(client, session, name, args) -> str: ...
```

**预计行数**：~150 行（含 docstring + 注释）

---

### 3.2 `mcp/client.py`（**新**）**—— **学**官**方** MCPClient per-session（**V2 #7.7 完**整**蓝**图**）**

**官**方**的** `MCPClient`（** 403 行**）**的**设**计**是** V2 #7.7 per-session MCP server 的**完**整**蓝**图**：

```python
# bridge/src/xiaozhi_bridge/mcp/client.py
class MCPClient:
    """Per-session MCP client (V2 #7.7 blueprint).

    Holds the per-session MCP state: discovered tools, name mapping,
    in-flight call futures, and a monotonic request id counter.
    Replaces the global _REGISTRY and session.pending_mcp_calls.

    Why per-session (vs global): solves the race condition we found
    in V2 #7.7 Bug 4 (global _REGISTRY overwritten across sessions).
    """

    def __init__(self):
        self.tools: dict[str, ToolDefinition] = {}  # sanitized name -> def
        self.name_mapping: dict[str, str] = {}  # bridge name -> esp32 name
        self.call_results: dict[int, asyncio.Future] = {}  # id -> Future
        self.next_id: int = 0
        self.ready: bool = False
        self._lock = asyncio.Lock()  # V2 #7.7 race fix

    async def register_tool(self, name: str, def: dict) -> None: ...
    async def has_tool(self, name: str) -> bool: ...
    async def get_available_tools(self) -> list[dict]: ...
    async def get_next_id(self) -> int: ...
    async def register_call_result(self, id: int, future: asyncio.Future) -> None: ...
    async def resolve_call_result(self, id: int, result: Any) -> None: ...
    async def reject_call_result(self, id: int, exc: Exception) -> None: ...
```

**SessionContext 加** `mcp_client: MCPClient` **字**段**（**替**换** pending_mcp_calls + mcp_request_id**）**。

**修**复** Bug 4 race condition 的**完**整**路**径**。

**预**计**行**数**：~150 行。

---

### 3.3 `mcp/manager.py`（**新**）**—— **学**官**方** UnifiedToolManager（**解**决** Bug 4 全**局**注**册**）**

**官**方**的** `UnifiedToolManager`（** 200+ 行**）**的**设**计**把**全**局** dict 升**级**为**注**册**表** + 派**发**器**：

```python
# bridge/src/xiaozhi_bridge/mcp/manager.py
class ToolType(StrEnum):
    """V2 #7.7: tool categorization for executor dispatch."""
    DEVICE = "device"      # esp32-side (V2 #7)
    FUNCTION = "function"  # bridge local (V1)
    # SERVER = "server"   # future (web_search / get_weather)
    # IOT = "iot"         # future (HA / mqtt)


class ToolExecutor(Protocol):
    """V2 #7.7: per-tool-type executor interface."""
    tool_type: ToolType
    async def execute(self, conn, session, name: str, args: dict) -> Any: ...
    def get_tools(self) -> dict[str, ToolDefinition]: ...


class ToolManager:
    """V2 #7.7: registry + dispatch for tool executors."""
    def __init__(self) -> None:
        self.executors: dict[ToolType, ToolExecutor] = {}
        self._cache: dict[str, ToolExecutor] | None = None
    def register_executor(self, type: ToolType, executor: ToolExecutor) -> None: ...
    def get_executor(self, name: str) -> ToolExecutor | None: ...
    async def execute_tool(self, conn, session, name: str, args: dict) -> Any: ...
```

**mcp/handlers.py 改**为**薄**的** DeviceMCPExecutor**（** ~50 行**）**，**注**册**到** ToolManager**。**FunctionToolExecutor 另**开**。**Bug 4 race condition **不**再**存**在**（**每**个**工**具**有**自**己**的** Executor，**不**会**全**局**覆**盖**）**。

**预**计**行**数**：~180 行。

---

### 3.4 `handle/textHandler/*.py`（**新**目**录**）**—— **学**官**方**按**消**息**类**型**拆**（**替**换** _main_loop match-case**）**

**官**方**的**核**心**设**计** —— **每**个**消**息**类**型**有**单**独**的** `XxxTextMessageHandler` 类**：

```
bridge/src/xiaozhi_bridge/handle/
├── __init__.py
├── textMessageHandler.py        # abstract base (~30 行)
├── textMessageHandlerRegistry.py # 注册表 (~50 行)
├── textMessageProcessor.py       # 派发器 (~50 行)
└── textHandler/
    ├── __init__.py
    ├── helloMessageHandler.py    # server_hello 握手 (~50 行)
    ├── listenMessageHandler.py   # listen 状态机 (~80 行)
    ├── abortMessageHandler.py    # abort 中断 (~20 行)
    └── mcpMessageHandler.py      # MCP 协议路由 (~80 行)
```

**官**方**的**基**类**：

```python
# bridge/src/xiaozhi_bridge/handle/textMessageHandler.py
class TextMessageHandler(ABC):
    """Abstract base for all xiaozhi text message handlers.

    Each handler is responsible for ONE message type. Dispatched
    by TextMessageProcessor via TextMessageHandlerRegistry.
    """
    message_type: str  # subclass sets this

    @abstractmethod
    async def handle(self, conn: "XiaozhiBridgeServer", message: dict) -> None: ...
```

**注**册**表** + 派**发**器** 替**换** _main_loop 的** match-case**：

```python
# 拆**分**前** (server.py _main_loop 30 行**)**：
match msg:
    case ListenMessage(): await self._handle_listen(...)
    case AbortMessage(): await self._handle_abort(...)
    case MCPMessage(): await self._handle_mcp(...)
    # ... 加**新**消**息**类**型** = 改** server.py

# 拆**分**后** (server.py 3 行**)**：
await message_processor.process_message(self, raw)
# 加**新**消**息**类**型** = 加** handler + register_handler
```

**预**计**行**数**：~360 行（** 8 个**文**件**）**。

---

### 3.5 `pipeline/turn.py`（**新**）

**目标**：把 ASR → LLM tool-use 循环 → TTS **整条业务流水线**抽到独立模块。

| 来源（server.py）| 行 | 抽到 turn.py |
|---|---|---|
| `_process_turn` | 43 | `TurnPipeline.process(asr, llm, tts, ws, session, text)` |
| `_process_text` | 158 | `TurnPipeline.process_text(llm, mcp_handler, tts_pipeline, ws, session, text)` |

**结构**：
```python
# bridge/src/xiaozhi_bridge/pipeline/turn.py
class TurnPipeline:
    """V2 #7: ASR → LLM (with optional tool calls) → TTS turn pipeline.

    Composes 3 downstream modules: ASR (already abstracted), LLM
    (already abstracted), and TTS (delegated to TTSPipeline).

    All methods are async coroutines that take a "server" loosely
    typed reference for access to the sessions / DB / log.
    """
    @staticmethod
    async def process(server, ws, session, text) -> None
    @staticmethod
    async def process_text(server, ws, session, text) -> None
    @staticmethod
    async def _dispatch_tool_call(server, session, tc) -> str
```

**核心**：
- `_process_text` 里的 tool-use 循环（max 5 iterations）原样搬到 `process_text`
- 调用 `ToolManager.execute_tool`（替代 `_dispatch_tool`）
- 调用 `TTSPipeline.send` 而不是 `self._send_tts`

**v0.2.11 的所有 V2 #7 E2E 测试 0 改**（只改 import 路径 + 重命名 `_process_text` → `process_text`）。

**预计行数**：~280 行

---

### 3.6 `pipeline/tts.py`（**新**）

**目标**：把 TTS 串流协议（`tts.start` → `tts.sentence_start` → Opus → `tts.stop`）抽到独立模块。

| 来源（server.py）| 行 | 抽到 tts.py |
|---|---|---|
| `_send_tts` | 86 | `TTSPipeline.send(tts_provider, ws, session, text)` |

**结构**：
```python
# bridge/src/xiaozhi_bridge/pipeline/tts.py
class TTSPipeline:
    """TTS streaming pipeline (text → tts.start/sentence_start/Opus/tts.stop).

    Handles state transitions, ConnectionClosed gracefully (V2 #8.4),
    and persists the assistant turn to DB after successful TTS
    (V2 #3).
    """
    @staticmethod
    async def send(server, ws, session, text) -> None
```

**v0.2.8 的 ConnectionClosed 处理（V2 #8.4）+ v0.2.11 的 record_conversation 包裹**都**搬**过**去**。

**预计行数**：~110 行

---

### 3.7 `audio/handler.py`（**新**）

**目标**：把 VAD + Opus 解码 + 缓冲区管理抽到独立模块。

| 来源（server.py）| 行 | 抽到 handler.py |
|---|---|---|
| `_handle_audio` | 66 | `AudioHandler.handle(vad, codecs, ws, session, opus_frame)` |
| `_handle_listen` | 41 | `AudioHandler.handle_listen(vad, asr, ws, session, msg)` |
| `_end_wake_grace` | 13 | `AudioHandler.end_wake_grace(vad, session)` |
| `_cancel_wake_grace` | 22 | `AudioHandler.cancel_wake_grace(server, session)` |

**结构**：
```python
# bridge/src/xiaozhi_bridge/audio/handler.py
class AudioHandler:
    """V2 #8.3: Opus decode + server-side Silero VAD + voice segment routing.

    Pulls audio frames from the device, runs VAD, and on voice_stop
    calls the registered ASR provider. Encapsulates the
    wake-grace window logic (V2 #8.3: 2s grace after wake word to
    avoid false VAD positives).
    """
    @staticmethod
    async def handle(server, ws, session, opus_frame) -> None
    @staticmethod
    async def handle_listen(server, ws, session, msg) -> None
    @staticmethod
    async def end_wake_grace(vad, session) -> None
    @staticmethod
    def cancel_wake_grace(server, session) -> None
```

**预计行数**：~180 行

---

## 4. 拆分后 server.py 瘦身目标

| 版本 | server.py 行 | 内容 |
|---|---|---|
| v0.2.12（**今**天**）| **1124** | 全部混合 |
| v0.2.13（**拆**分**）| **~280** | 只**留** server 生命周期：start / stop / _handle_connection / _main_loop（3 行**派**发**）** / _transition + 装配 |

**瘦身后 server.py 25% 行数**（280/1124），**业务流水线全部分布到 8 个新文件**。

---

## 5. 拆分前后目录结构对比

```
bridge/src/xiaozhi_bridge/
├── server.py            # 1124 → 280 行（lifecycle only）
├── main.py              # 104 行（不变）
├── config.py            # 243 行（不变）
├── api/                 # HTTP API（不变）
│   ├── main.py          # 424
│   └── db.py            # 601
├── asr/                 # ASR providers（不变）
│   ├── base.py
│   ├── mock.py
│   ├── sherpa_onnx.py
│   ├── sensevoice.py
│   └── cloud.py
├── tts/                 # TTS providers（不变）
│   ├── base.py
│   ├── mock.py
│   ├── edge.py
│   └── cloud.py
├── llm/                 # LLM clients（不变）
│   ├── base.py
│   ├── openclaw.py
│   └── prompts.py
├── vad/                 # VAD providers（不变）
│   ├── base.py
│   └── silero.py
├── mcp/                 # 🆕 + 3 个新文件
│   ├── __init__.py
│   ├── server.py        # 172（不变）
│   ├── tools.py         # 307 → ~200（拆分）
│   ├── client.py        # 🆕 ~150 行（MCPClient per-session）
│   ├── manager.py       # 🆕 ~180 行（ToolManager）
│   └── handlers.py      # 🆕 ~150 行（DeviceMCPExecutor）
├── handle/              # 🆕 整目录（学官方 textHandler）
│   ├── __init__.py      # 🆕
│   ├── textMessageHandler.py        # 🆕 ~30 行
│   ├── textMessageHandlerRegistry.py # 🆕 ~50 行
│   ├── textMessageProcessor.py      # 🆕 ~50 行
│   └── textHandler/                 # 🆕
│       ├── __init__.py
│       ├── helloMessageHandler.py   # 🆕 ~50 行
│       ├── listenMessageHandler.py  # 🆕 ~80 行
│       ├── abortMessageHandler.py   # 🆕 ~20 行
│       └── mcpMessageHandler.py     # 🆕 ~80 行
├── pipeline/            # 🆕 整目录
│   ├── __init__.py      # 🆕
│   ├── turn.py          # 🆕 ~280 行（ASR→LLM→TTS）
│   └── tts.py           # 🆕 ~110 行（TTS 协议）
├── audio/               # 🆕 整目录
│   ├── __init__.py      # 🆕
│   └── handler.py       # 🆕 ~180 行（VAD+Opus+listen）
├── protocol/            # 协议层（不变）
│   ├── messages.py      # 185
│   ├── states.py        # 137
│   └── audio.py         # 146
└── utils/               # 工具（不变）
    └── logging.py       # 62
```

**新**增** 8 个**文**件** + 4 个** \_\_init\_\_.py = 12 个**新**文**件**，**总**行**数** +300 行**（新**文**件**的 import 块 + 模块级 docstring + handle/ 的 4 个 handler 各 ~80 行**）。

---

## 6. 拆**分**对**后**期**的**影**响**

### 6.1 正**向**（**能**解**决**的**问**题**）

| 问**题** | 拆**分**前** | 拆**分**后** |
|---|---|---|
| **server.py 修**改**难**度** | 主**类** + 13 方法，**改**任**何**一**处**要**读**全**部** | lifecycle **只** ~280 行，**改**连**接**握**手** / **主**循**环**只**读** ~280 行 |
| **加**新**消**息**类**型** | 改** server.py match-case | 加** XxxMessageHandler + register |
| **mcp 模**块**独**立**演**化** | 全**局** dict + race condition | per-session MCPClient + async Lock + ToolManager 派**发** |
| **pipeline 单**测** | 要**起** server 实**例**，**mock 12 个**属**性** | 调** TurnPipeline.process(server_mock)，**server 是** Protocol**，**只**需** mock 4 个**属**性**|
| **V2 #7.7 per-session MCP** | 要**改** server.py + 加**新** race condition | **只**改** mcp/client.py，server.py **碰**都**不**用**碰** |
| **V2 #12 替**换** openclaw 为** 直**接** anthropic API** | 要**改** server.py + llm/openclaw.py | **只**改** llm/ + pipeline/turn.py，server.py **碰**都**不**用**碰** |
| **V2 #13 加** WebRTC 替**换** Opus** | 要**改** server.py + protocol/audio.py | **只**改** audio/handler.py + protocol/audio.py，server.py **碰**都**不**用**碰** |
| **V2 #14 接** HA / 米家** / MQTT** | 改** server.py + 4 个**新** Provider | **只**改** providers/ + 1 个**新** Executor + register |

### 6.2 负**向**（**新**引**入**的**问**题**）

| 问**题** | 严**重**度** | 缓**解** |
|---|---|---|
| **新**手**找**代**码**要**多**跳**一**层** | 🟢 低（**文**档**化**后**找**得**到**） | docs/architecture.md 加**模**块**依**赖**图** |
| **`server` 参**数**变**成**"魔**法**对**象**"** | 🟡 中（**类**型**不**明**） | 加** `class ServerProtocol(Protocol)` **在** types.py **里**明**确**接**口** |
| **import 循**环**风**险** | 🟡 中（pipeline → server → pipeline） | **只**传** server **作**为**参**数**，**不**在** pipeline **里** import server |
| **测**试**文**件**碎**片** | 🟢 低（**加** 4 个** test_*.py）** | 文**档** + pyproject.toml 分**组** |
| **拆**分** PR **大**（**~14 文**件**）| 🟡 中 | **分** 3 阶**段** commit（**下**文** §7**）|

---

## 7. 实**施**计**划**（**分** 3 阶**段**）

### 阶**段** 1：抽** mcp/{client,manager,handlers}.py + mcp/tools.py 拆**分**（**V2 #7.7 完**整**蓝**图**）**

- **新**建** `bridge/src/xiaozhi_bridge/mcp/client.py`（**~150 行**）**：MCPClient per-session
- **新**建** `bridge/src/xiaozhi_bridge/mcp/manager.py`（**~180 行**）**：ToolType + ToolExecutor + ToolManager
- **新**建** `bridge/src/xiaozhi_bridge/mcp/handlers.py`（**~150 行**）**：DeviceMCPExecutor
- **拆** `bridge/src/xiaozhi_bridge/mcp/tools.py` 307 行** → 只**留** FunctionTool + register_tool（**~200 行**）
- **修** server.py 改**为** ToolManager.execute_tool 调**用**
- **修** SessionContext 加** mcp_client 字**段**
- **修**测**试** import 路**径**（**只**改** import，**0 逻**辑**变**化**）**
- **跑** ruff + mypy + pytest（**期**待**：165 + 6 = 171 全**过**）**

**预计**：**2-3 hr**。**危**险**度**：**🟡 中**（修**复** Bug 4 race condition 的**完**整**路**径**）。**版**本**：v0.2.13a。

### 阶**段** 2：抽** handle/ 整**个**目**录**（**学**官**方**按**消**息**类**型**拆**）**

- **新**建** `bridge/src/xiaozhi_bridge/handle/` + 8 个**新**文**件**（**~360 行**）**
- **拆** _handle_hello / _handle_listen / _handle_abort / _handle_mcp 4 段**到** textHandler/*.py
- **修** _main_loop 改**为** 3 行**派**发**（**await message_processor.process_message**）**
- **跑** CI 套

**预计**：**2-3 hr**。**危**险**度**：**🟡 中**（要**改** _main_loop 的**调**用**链**）。**版**本**：v0.2.13b。

### 阶**段** 3：抽** pipeline/{turn,tts}.py + audio/handler.py**（**剩**下**的** ~600 行**）**

- **新**建** `pipeline/{turn.py + tts.py}` + `audio/handler.py`（**~570 行**）**
- **修** server.py 改**为** thin caller
- **跑** CI 套 + **重**新**部**署** + **验**证** VPS `/api/health` 0.2.13c**

**预计**：**2-3 hr**。**危**险**度**：**🟢 低**（剩**下**的**是** helper 抽**离**）**。**版**本**：v0.2.13c。

---

## 8. 后**期**维**护**规**范**（**学**官**方** + 8 条**新**铁**律**）**

| # | 规**范** | 举**例** |
|---|---|---|
| 1 | **改** ASR = **只**改** `asr/`** | 加** Whisper.cpp 支**持** = **新**建** `asr/whisper_cpp.py` |
| 2 | **改** TTS = **只**改** `tts/`** | 加** 火山 TTS = **新**建** `tts/volcengine.py` |
| 3 | **改** LLM = **只**改** `llm/`** | 加** anthropic 直**接** API = **新**建** `llm/anthropic.py` |
| 4 | **改** MCP 协议** = 只**改** `mcp/`**（**handlers + server + tools**）** | V2 #7.7 per-session MCP = **只**改** `mcp/client.py` |
| 5 | **改** ASR→LLM→TTS 流**水**线** = 只**改** `pipeline/`** | 加** streaming-first LLM = **只**改** `pipeline/turn.py` |
| 6 | **改** 音频**处**理** = 只**改** `audio/`** | 加** WebRTC 替**换** Opus = **只**改** `audio/handler.py` |
| 7 | **改** WS 握**手** / 主**循**环** = 只**改** `server.py`** | 加** v2.0 协议** = 只**改** server.py 4 个**方**法** |
| 8 | **改** 消**息**类**型** = 加** `handle/textHandler/XxxMessageHandler` + register** | 加** `iot` 消**息** = 新**建** `iotMessageHandler.py` + register |
| 9 | **改** 状**态**机** / 消**息** schema** = 只**改** `protocol/`** | 加** ServerHello v2 = **只**改** `protocol/messages.py` |

**简**而**言**之**："**改**业**务** 找**专**业**模**块**，**改**协**议** 找** server.py / protocol/**，**改**消**息**流** 找** handle/**"。

---

## 9. 风**险** + 缓**解**

| 风**险** | 缓**解** |
|---|---|
| **拆**分**期**间**会**话**状**态**机**错**位** | **拆**分**前**先**跑** 171 测**试**绿**线**；**拆**分**后**必**跑** ruff + mypy + pytest |
| **现**有** _main_loop **改**成** thin caller** 后**断**路** | **保**留** server.py 旧**方**法**作**为** shim**，**加** `# DEPRECATED, use PipelineFoo` 注**释**，**下**个** release **删** |
| **VPS 部**署** v0.2.13c 之**后** esp32 链**路**变**差** | **先**在** 本**地** + headless **跑** 171 测**试**，**再**部**署** |
| **拆**分** PR 大**，**不**好** review** | **分** 3 阶**段** commit（v0.2.13a/b/c），**单**独** PR** |
| **借**鉴**官**方** ToolType 抽**象**会**让** mcp/tools.py 拆**成** 4 文**件** | **严**格**按**官**方**来**（**base / manager / handler / executor**）**，**不**自**创** |

---

## 10. **不**拆**的**部**分**

- **不**拆** `protocol/`** —— 现状**完**美**（messages / states / audio 各**司**其**职**）**
- **不**拆** `api/db.py` 601 行** —— DB CRUD **天**然**长**（**如**果**到** 1000+ **再**拆**）**
- **不**拆** `api/main.py` 424 行** —— HTTP API **路**由** 1 个**文**件**合**理**
- **不**拆** `asr/sherpa_onnx.py` / `tts/edge.py`** —— **单** provider **可**以** 300 行**，**拆**了**反**而**碎**
- **不**重**写** `__init__` 65 行** —— **装**配** server **状**态**的**唯**一**地**方**，**合**理**

---

## 11. **问** Allen 的 6 个**决**策**点**

1. **v0.2.13a（mcp/client + manager + handlers）今**天**做**？**还**是** 明**天**做**？**（**2-3 hr**）**
2. **v0.2.13b（handle/ 整**个**目**录**）什**么**时**候**做**？**（**2-3 hr**）**
3. **v0.2.13c（pipeline/ + audio/）什**么**时**候**做**？**（**2-3 hr**）**
4. **是**否**接**受** server.py **从** 1124 **瘦**身**到** ~280 行**但** import 增**多**？**（**接**受** 0 风**险**，**不**接**受** 0 改**动**）**
5. **是**否**接**受**借**鉴**官**方**的** ToolType 抽**象**拆** mcp/tools.py **为** 4 个**文**件**？**（**接**受** 修**复** Bug 4 race condition）**
6. **是**否**要**求** refactor PR **带** before/after **行**数** + 测**试**通**过**截**图** + 实**测** VPS `/api/health` 0.2.13c？**（**我**建**议** 必**要**）**

---

## 12. 一**页**纸**总**结**

- **现**在**：server.py **一**个**文**件** 1124 行**，**业**务**混**在**主**类**。
- **拆**分**后**：server.py **只** 280 行**（lifecycle），**8 个**新**文**件**（**6 个**新**模**块**）** = **~1390 行**（**business**）**。
- **好**处**：**改** ASR **不**动** server.py**，**改** MCP **不**动** audio.py**，**改** pipeline **不**动** server.py**，**加**新**消**息**类**型** = 加** handler + register**。
- **坏**处**：**新**手**多**跳** 1-2 层**（**文**档**化**解**决**）**。
- **实**施**：**分** 3 阶**段** commit（v0.2.13a/b/c），**总** 6-9 hr。
- **后**期**：** 9 条**铁**律**，**每**条**对**应**一**个**模**块**，**改**什**么**找**什**么**模**块**。

---

## 附录 A：官方 vs 我们的架构对比图（文字版）

```
官**方**的**架**构**（**30K+ 行**）**                          我**们**的**架**构**（**5.8K 行**）**

ConnectionHandler (1661)                    XiaozhiBridgeServer (1124)
  ├─ handle/textHandler/* (4-7 文件)        ├─ _handle_listen (server.py 内)
  ├─ handle/textMessageHandlerRegistry       ├─ _handle_abort
  ├─ handle/textMessageProcessor             ├─ _handle_mcp
  │                                          ├─ _handle_audio
  │  （**每**个**消**息** 1 个** handler**）**              │  （**match-case in _main_loop**）**
  │                                          │
  ├─ providers/asr/* (17 文件)               ├─ asr/* (5 文件)
  ├─ providers/tts/* (22 文件)               ├─ tts/* (4 文件)
  ├─ providers/llm/*                         ├─ llm/* (3 文件)
  ├─ providers/vad/*                         ├─ vad/* (2 文件)
  │                                          │
  ├─ providers/tools/                        ├─ mcp/
  │  ├─ base.py (ToolType + ToolExecutor)    │  ├─ tools.py (FunctionTool + 全局 dict)
  │  ├─ unified_tool_manager.py (ToolManager) │  └─ server.py (MCP 协议)
  │  ├─ unified_tool_handler.py (Unified...)  │     （❌ 没**有** ToolType 抽**象**）**
  │  ├─ device_mcp/ (MCPClient + Executor)   │     （❌ 没**有** ToolManager 派**发**）**
  │  ├─ device_iot/                          │     （❌ 没**有** per-session MCPClient**）**
  │  ├─ server_mcp/                          │     （❌ Bug 4 race condition 未**修**）**
  │  ├─ server_plugins/                      │
  │  └─ mcp_endpoint/                        │
  │                                          │
  │  （**5 个** Executor 类**型**）**                       │  （** 1 个** FunctionTool + DeviceToolHandler**）**
  │  （**MCPClient per-session**）**                       │  （**全**局** _REGISTRY**）**
  │  （**asyncio.Lock**）**                                │  （**无** Lock**）**
```

**对**比**结**论**：
- 我**们**的**架**构**在** "**抽**象**层**"** 上**比**官**方**薄** ~50%（**没**有** ToolType 抽**象** + 没**有** ToolManager 派**发**）**。
- 我**们**的**架**构**在** "**消**息**路**由**"** 上**比**官**方**单**薄**（**match-case vs textHandler/*.py**）**。
- 我**们**的**架**构**在** "**provider 数**量**"** 上**比**官**方**少**（**asr 5 vs 17，tts 4 vs 22**）** —— 这**是** V3 阶**段**的**事**情**。
- 我**们**的**架**构**在** "**总**体**模**块**粒**度**"** 上**跟**官**方**接**近**（**每**个** provider / 工**具**是**独**立**文**件**）**，**但** "**连**接**层**"** （**server.py / connection.py**）**我**们**的**粒**度**粗**（**1124 vs 官**方** 1661**）**。
- **修**复** Bug 4 race condition 的**根**本**解**决**：**学**官**方**的** ToolManager + per-session MCPClient**。
- **加**新**消**息**类**型** / 加**新** Executor 类**型** / 加**新** Provider** = **只**改** 1 个**新**文**件** + register**。

---

## 附录 B：拆分后 server.py 250 行的样子（伪代码）

```python
# bridge/src/xiaozhi_bridge/server.py (v0.2.13c 拆分后, ~250 行)

class XiaozhiBridgeServer:
    def __init__(self, config: AppConfig):
        # 装配所有 provider + 工具
        self.asr = get_asr(...)
        self.tts = get_tts(...)
        self.llm = get_llm(...)
        self.vad = get_vad(...)
        self.mcp = MCPServer()
        # 工具管理 (学官方)
        self.tool_manager = ToolManager()
        self.tool_manager.register_executor(ToolType.FUNCTION, FunctionToolExecutor())
        self.device_mcp_executor = DeviceMCPExecutor()
        self.tool_manager.register_executor(ToolType.DEVICE, self.device_mcp_executor)
        # 内部状态
        self.sessions = {}
        self._codecs = {}
        # ...

    async def start(self): ...       # 40 行
    async def stop(self): ...        # 9 行
    async def serve_forever(self): ... # 13 行

    async def _handle_connection(self, ws):  # 80 行
        # 1. WS 握手 (V2 #8 / V2 #6.1)
        # 2. 构造 session (含 MCPClient per-session)
        # 3. 注册 device tools
        # 4. await self._main_loop(ws, session)
        # 5. finally: 清理 (含 MCPClient 关闭)

    async def _main_loop(self, ws, session):  # 5 行
        async for raw in ws:
            if isinstance(raw, bytes):
                await AudioHandler.handle(self, ws, session, raw)
            else:
                await message_processor.process_message(self, raw)

    async def _transition(self, session, new_state): ...  # 10 行
    # 派发器（handle 目录）
    def _build_server_hello(self): ...  # 30 行（构造 server_hello 消息）
```

**总**行**数**：~250-280 行。**只**剩** server **生**命**周**期** + **装**配**。
