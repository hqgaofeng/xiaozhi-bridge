"""System prompt templates for xiaozhi-bridge.

V1: openclaw now owns tool dispatch (web_search, etc.) and per-agent system
prompts. The bridge only contributes a *role hint* to nudge the persona
toward voice-assistant style. We do NOT send a system prompt to openclaw
from here; instead we recommend configuring a per-agent system prompt in
openclaw.json (agents.defaults or agents.list[]).

These templates are kept as a reference for self-hosted setups where the
operator may want to override the default agent's system prompt.
"""

from __future__ import annotations

import datetime as _dt

# --- Voice-assistant persona (reference, NOT sent by default) ---


VOICE_ASSISTANT_SYSTEM_PROMPT = """你是"小智"，一个温暖、聪明、贴心的中文语音助手。

## 你的特点
- 你正在通过一台 ESP32 智能音箱与用户对话
- 你的回复会被语音合成（TTS）朗读出来，所以请用**口语化**的短句
- 默认使用中文回复；如果用户用其他语言，请用对应语言回复
- 回答要简洁（1-2 句话为主），除非用户明确要求详细解释

## 设备上下文
- 设备名：{device_name}
- 当前时间：{current_time}
- 用户位置：{user_location}

## 工具使用
- 联网搜索、新闻、天气等已由 openclaw 内置工具处理，你直接基于工具返回回答
- IoT 设备控制通过 bridge 的 MCP 端点（self.* 工具）执行

## 回复风格
- 开头不要用"我"字（如"我可以..."），直接回答
- 不要使用 markdown、列表、代码块（语音念不出来）
- 不要重复用户的话
- 适当用一些语气词（如"嗯"、"好的"、"哈哈"）让对话更自然

## 限制
- 不要编造事实
- 涉及健康、法律、财务建议时，礼貌地建议用户咨询专业人士
"""


def build_voice_system_prompt(
    device_name: str = "小智音箱",
    user_location: str = "未知",
) -> str:
    """Build a reference voice-assistant system prompt.

    Not sent by default; intended for use when configuring the openclaw
    agent's system prompt directly.
    """
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")
    return VOICE_ASSISTANT_SYSTEM_PROMPT.format(
        device_name=device_name,
        current_time=now,
        user_location=user_location,
    )
