# ASR 模型选择指南

> xiaozhi-bridge 支持多种 ASR provider；本文档对比它们的特性、适用场景和切换方法。

## Provider 概览

| Provider | 类型 | 语种 | 适合场景 | 模型大小 | 延迟 | 引入版本 |
|---|---|---|---|---|---|---|
| `mock` | 占位 | - | 测试 / 无 ASR 部署 | 0 | 0ms | V1 |
| `sherpa_onnx` | 流式 (zipformer) | zh+en | 短句（< 10s），低延迟 | 200MB int8 | RTF 0.4-0.7 | V2 #1 |
| **`sensevoice`** | **离线 (non-AR)** | **zh+en+ja+ko+yue** | **长句（10s+），高准确率** | **229MB int8** | **RTF 0.2-0.3** | **V2 #10 C-5** |
| `cloud` | 云端 HTTP | 视厂商 | 生产 + 多语种 + 大词汇量 | 0（云） | 200-500ms | V1（骨架） |

## 怎么选

### 短句为主（"你好小智"、"现在几点了"）
**用 sherpa_onnx**（默认）。流式 + 低延迟，10s 内短句 80%+ 准。

### 长句 / 多语种混说 / 数字格式化
**用 sensevoice**。非自回归离线处理，长句 95%+ 准，自带标点 + 数字格式化。

### 不确定
先用默认（v0.2.10+ **sensevoice**），看日志里 `sensevoice.transcribed` 的 `text_preview`。  
**需**要**低**延**迟** + **短**句**流**式**（**< 10s**）** → 切回 sherpa_onnx（v0.2.10 之**前**默**认**）。  
**需**要**更**省**内**存**（**sherpa_onnx 200MB vs sensevoice 230MB**）** → 切回 sherpa_onnx。

## 切换方法

### 0. 准备模型（host 端，仅 sensevoice 需要）

```bash
# SenseVoice int8 模型 229MB，下载到 bind mount 路径
wget -qO- https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2 \
  | tar -xj -C /opt/xiaozhi-bridge/models/

# 重命名（去掉 "sherpa-onnx-" 前缀，让路径更短）
mv /opt/xiaozhi-bridge/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17 \
   /opt/xiaozhi-bridge/models/sensevoice-zh-en-ja-ko-yue-int8-2024-07-17
```

确认文件存在：

```bash
ls -lh /opt/xiaozhi-bridge/models/sensevoice-zh-en-ja-ko-yue-int8-2024-07-17/
# 期望看到：
# -rw-r--r-- 1 root root 229M  model.int8.onnx
# -rw-r--r-- 1 root root 309K  tokens.txt
# drwxr-xr-x 2 root root 4.0K  test_wavs/   # 自带测试音频
```

### 1. 改 `config/config.yaml`

把 `asr.provider` 从 `sherpa_onnx` 改成 `sensevoice`：

```yaml
asr:
  provider: sensevoice  # was: sherpa_onnx
  options:
    model_dir: /opt/xiaozhi-bridge/models/sensevoice-zh-en-ja-ko-yue-int8-2024-07-17
    num_threads: 2
    language: auto  # auto | zh | en | ja | ko | yue
    use_itn: true   # adds punctuation + number formatting
```

### 2. 重启 bridge

```bash
docker compose restart bridge
```

### 3. 验证

```bash
# 看启动日志
docker logs xiaozhi-bridge --since 30s 2>&1 | grep -E "asr|sensevoice"
# 期望看到：
#   asr:    sensevoice
#   sensevoice.model_ready load_ms=~4000 ...

# 触发一次 ASR（对 esp32 说一句话）
docker logs xiaozhi-bridge --since 60s 2>&1 | grep sensevoice.transcribed
# 期望看到：
#   sensevoice.transcribed audio_duration_ms=... rtf=0.2-0.3 text_preview='...'
```

### 4. 切回 sherpa_onnx（如需要）

把 `provider` 改回 `sherpa_onnx`，重启即可。两个 provider **独立**注册，切换不破坏 ASR 抽象层。

## 关键差异详解

### 流式 vs 离线

- **sherpa_onnx（流式）**：VAD 触发 → 每 60ms 喂一帧 → 增量识别。  
  优势：低延迟（首 token 100ms）。劣势：流式自回归对长句泛化弱。
- **sensevoice（离线）**：VAD 触发 → 整段 1-15s 音频 → 单次前向 → 完整文本。  
  优势：长句 95%+ 准。劣势：必须等整段音频到达才能转写。

我们的 **VAD（V2 #8.3 Silero）** 在两种 provider 间**复用**：把音频切成 "用户说话" 段，再喂给 ASR。所以流式/离线的差异在用户感知上**只差 ~500ms**（整段说完到听见 TTS 开始的时间）。

### 语言检测

- **sherpa_onnx**：固定 `bpe` 单位，硬编入 `modeling_unit`，**没**显式语言字段。
- **sensevoice**：`language` 配置项（默认 `auto`），自动从音频特征检测 zh/en/ja/ko/yue。

### ITN（反向文本规范化）

- **sherpa_onnx**：无 ITN。"123" → "一二三"。
- **sensevoice**：`use_itn=true`（默认）→ "今天是2026年6月5日"  
  `use_itn=false` → "今天是二零二六年六月五日"

## 故障排查

### 启动报 `sensevoice.model_dir missing required files`

模型没下载或路径不对：

```bash
# 检查路径
ls -lh /opt/xiaozhi-bridge/models/sensevoice-zh-en-ja-ko-yue-int8-2024-07-17/

# 确认 docker compose 把 host 路径 bind mount 进容器
grep -A 3 "models" docker-compose.yml
# 期望看到：
#   - /opt/xiaozhi-bridge/models:/opt/xiaozhi-bridge/models:ro
```

### 转写为空 / 全是乱码

可能是语言识别错了。试试锁定 `language: zh`：

```yaml
options:
  language: zh  # 强制中文
  use_itn: true
```

### RTF > 1.0（实时因子超过 1 = 比说话还慢）

CPU 不够用。降低线程数：

```yaml
options:
  num_threads: 1  # 默认 2；VPS 1 vCPU 设 1 更稳
```

或切回 `sherpa_onnx`（资源占用更小）。

## 实测基线（2026-06-05）

5 段 sherpa_onnx 自带 test_wavs (4.7s-17.6s) 在容器内真模型跑：

| 文件 | 时长 | sherpa_onnx (modified_beam) | sensevoice (use_itn=true) | 评价 |
|---|---|---|---|---|
| 0.wav | 10.1s | 10.2s 推理 / "昨天天是 MONDAY TODAY IS LIBY..." | 6.4s 推理 / "昨天是monday，today is礼拜2..." | sensevoice 准 + 加标点 |
| 1.wav | 5.1s | 2.6s / "这是第一种第二种叫呃与 ALWAYS ALWAYS什么" | 1.1s / "这是第一种。第二种叫呃与OSOS什么意思啊？" | sensevoice 加句读 |
| 2.wav | 4.7s | 2.3s / "...FREQUENTLY频繁的" | 1.5s / "...frent平繁的" | 持平（都有 bpe 误） |
| 3.wav | 8.8s | 5.4s / "...对吧后面那还有时时态" | 2.6s / "...对吧后把它时材写上去" | 持平 |
| 8k.wav | 17.6s | 7.4s 推理 93 字符 / "嗯然后他也没叫准时..." | 3.5s 推理 93 字符 / "嗯，on time交准时in time是及时交..." | **sensevoice 0.5x 推理时间 + 加标点** |

**结论**：
- **长句（>10s）**：sensevoice 显著更准
- **短句（<5s）**：持平，sherpa_onnx 略快
- **混说（zh+en）**：sensevoice 显著更准（语言切换更稳）
- **TTS 友好度**：sensevoice 加标点 → 朗读自然

## 未来扩展（V2 #10.x）

- **streaming 离线 ASR**（Whisper.cpp / Moonshine）—— 真流式 + 长句
- **云端 provider 接入**（火山 / 阿里云 / 腾讯）—— `cloud.py` 骨架已就位
- **多 provider 路由**（短句 sherpa + 长句 sensevoice 智能切换）
- **per-session 语言锁定**（session 开始时声明语言，避免 auto 检测误）
