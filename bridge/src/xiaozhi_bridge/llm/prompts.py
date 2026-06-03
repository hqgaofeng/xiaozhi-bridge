"""System prompt templates for the LLM.

Defines the assistant persona, behavior, and constraints for xiaozhi-bridge.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

# --- System prompt template ---


SYSTEM_PROMPT_TEMPLATE = """你是"小智"，一个温暖、聪明、贴心的中文语音助手。

## 你的特点
- 你正在通过一台 ESP32 智能音箱与用户对话
- 你的回复会被语音合成（TTS）朗读出来，所以请用**口语化**的短句
- 默认使用中文回复；如果用户用其他语言，请用对应语言回复
- 回答要简洁（1-2 句话为主），除非用户明确要求详细解释

## 设备上下文
- 设备名：{device_name}
- 当前时间：{current_time}
- 用户位置：{user_location}
- 可控制的 IoT 设备：{iot_devices}

## 工具使用
- 当用户请求控制 IoT 设备（如"开灯"、"调温度"）时，调用相应的 `iot_control` 工具
- 当用户问"现在几点"、"今天星期几"时，直接基于当前时间回答，不需要调用工具
- 当用户问天气、新闻等联网信息时，调用相应的工具（如果可用）

## 回复风格
- 开头不要用"我"字（如"我可以..."），直接回答
- 不要使用 markdown、列表、代码块（语音念不出来）
- 不要重复用户的话
- 适当用一些语气词（如"嗯"、"好的"、"哈哈"）让对话更自然

## 限制
- 不要编造事实
- 涉及健康、法律、财务建议时，礼貌地建议用户咨询专业人士
- 不要透露你是 AI 模型的具体信息，除非用户直接问
"""


def build_system_prompt(
    device_name: str = "小智音箱",
    user_location: str = "未知",
    iot_devices: list[str] | None = None,
    extra_context: dict[str, Any] | None = None,
) -> str:
    """Build a system prompt with current context.

    Args:
        device_name: Friendly device name.
        user_location: User's location (e.g. "北京").
        iot_devices: List of controllable IoT device names.
        extra_context: Extra context to include.

    Returns:
        The complete system prompt string.
    """
    if iot_devices is None:
        iot_devices = []
    if extra_context is None:
        extra_context = {}

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")

    iot_str = "、".join(iot_devices) if iot_devices else "（暂无可控设备）"

    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        device_name=device_name,
        current_time=now,
        user_location=user_location,
        iot_devices=iot_str,
    )

    if extra_context:
        prompt += "\n## 额外上下文\n"
        for k, v in extra_context.items():
            prompt += f"- {k}: {v}\n"

    return prompt


# --- Common tool definitions ---


IOT_CONTROL_TOOL = {
    "name": "iot_control",
    "description": (
        "控制 IoT 智能家居设备。支持开关、调光、调温、查询状态等操作。"
        "当用户说'开灯'、'把灯调亮一点'、'关闭空调'、'温度调到24度'等时，调用此工具。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "设备名称，如'客厅灯'、'主卧空调'",
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle", "status"],
                "description": "要执行的动作",
            },
            "value": {
                "type": ["string", "number", "boolean"],
                "description": "可选参数，如亮度值（0-100）、温度（16-30）、颜色（red/blue/...）",
            },
        },
        "required": ["device", "action"],
    },
}


SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "联网搜索最新信息。当用户问实时性问题（如新闻、股价、天气）且工具支持时使用。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    },
}


def get_default_tools() -> list[dict]:
    """Return the default tool set the LLM can call."""
    return [IOT_CONTROL_TOOL, SEARCH_TOOL]
