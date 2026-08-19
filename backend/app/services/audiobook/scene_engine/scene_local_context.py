"""Seed 场景局部描述构造（指导文档 §7.1）。

不把整章摘要原样传给所有场景。每个场景按以下优先级构造局部描述：

1. ``SeedSceneDirection.context``（阶段 3 导演输出，入口以 direction_context 传入）；
2. 当前 source segments 的 ``instruct_scene``（去重、按序合并）；
3. 章节结构化摘要中的时间、地点和情绪事实（``chapter_facts``）；
4. AudioDirector 的章节风格兜底（``director_style``）；
5. 最终兜底文案（``GENERIC_SCENE_FALLBACK_DESCRIPTION``）。

构造结果由 planner 逐场景注入 Prompt，随 prompt_hash 进入计划与 checkpoint 签名。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .prompt_compiler import GENERIC_SCENE_FALLBACK_DESCRIPTION

# chapter_facts 事实键：time（时间）、location（地点）、mood（情绪）。
# 构造为句式描述，避免带前缀标签（会被 voice_identity_policy 的 sanitize 剥离）。


def build_scene_local_description(
    segments: Sequence[Any],
    *,
    direction_context: str = "",
    chapter_facts: Mapping[str, Any] | None = None,
    director_style: str = "",
) -> str:
    """按 §7.1 优先级为一个场景构造局部描述；无上下文时返回最终兜底文案。"""
    direction = str(direction_context or "").strip()
    if direction:
        return direction

    scenes: list[str] = []
    for segment in segments:
        value = str(getattr(segment, "instruct_scene", "") or "").strip()
        if value and value not in scenes:
            scenes.append(value)
    if scenes:
        return "；".join(scenes)

    resolved_facts = chapter_facts if isinstance(chapter_facts, Mapping) else {}
    time_value = str(resolved_facts.get("time") or "").strip()
    location_value = str(resolved_facts.get("location") or "").strip()
    mood_value = str(resolved_facts.get("mood") or "").strip()
    sentence = ""
    spatial_parts = [value for value in (time_value, location_value) if value]
    if spatial_parts:
        sentence = "本章发生在" + "，".join(spatial_parts) + "。"
    if mood_value:
        sentence += ("整体氛围" if sentence else "本章整体氛围") + f"是{mood_value}。"
    if sentence:
        return sentence

    style = str(director_style or "").strip()
    if style:
        return style

    return GENERIC_SCENE_FALLBACK_DESCRIPTION


__all__ = [
    "GENERIC_SCENE_FALLBACK_DESCRIPTION",
    "build_scene_local_description",
]
