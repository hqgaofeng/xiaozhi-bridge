# 更新日志

> xiaozhi-bridge 版本变更记录
>
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased] - V1 开发中

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
