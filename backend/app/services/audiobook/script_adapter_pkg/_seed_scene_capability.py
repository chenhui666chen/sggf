"""Seed Audio 场景模式共享能力描述合同（指导文档阶段 1）。

分析与改编 Prompt 统一使用本模块的能力描述常量，不得硬编码供应商模型 ID；
真实模型 ID 由运行时配置决定。能力描述变化必须提升合同版本并按 DEC 登记。
"""

from __future__ import annotations

SEED_SCENE_CAPABILITY_CONTRACT_VERSION = "1.0.0"

# 首期最小文案：时间轴控制未开放前只声明可用性条件，不描述为已开放能力。
SEED_SCENE_CAPABILITY_DESCRIPTION = (
    "主生成路径：Seed Audio 完整声音场景模式，支持多角色、音效、音乐和声学空间；"
    "时间轴控制仅在运行时策略已通过契约验证并启用时可用；"
    "真实模型 ID 由运行时配置决定。"
)


def build_seed_scene_main_generation_block(sentence_tts_model: str) -> str:
    """构造分析与改编 Prompt 头部的主生成路径说明块。"""
    return (
        "**主生成路径：Seed Audio 完整声音场景模式**\n"
        f"- {SEED_SCENE_CAPABILITY_DESCRIPTION}\n"
        "- 负责在同一次生成中完成旁白、多人对白、非语言人声、环境、动作音效和配乐。\n"
        f"- 当前选择的逐句 TTS 模型 {sentence_tts_model} 仅用于试听参考音色和局部回退，不决定主场景剧本结构。\n"
    )


__all__ = [
    "SEED_SCENE_CAPABILITY_CONTRACT_VERSION",
    "SEED_SCENE_CAPABILITY_DESCRIPTION",
    "build_seed_scene_main_generation_block",
]
