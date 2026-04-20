from __future__ import annotations

import os
import re
from typing import Any, Dict, Literal, Optional, Tuple

from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model
from pipeline.media_presets import normalize_frame_ratio
from pipeline.style_presets import (
    normalize_style_preset,
    style_negative_prompt_for_preset,
    style_prompt_for_preset,
)

from app.services.dreamweaver.library import build_library_prompt


LibraryPromptMode = Literal["template", "ai"]

from app.services.dreamweaver.library_prompt_pkg._constants import *
from app.services.dreamweaver.library_prompt_pkg._utils import *
from app.services.dreamweaver.library_prompt_pkg._character_utils import *

def _merge_unique_segments(*parts: str, limit: int = 1400) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for raw in parts:
        text = str(raw or "").replace("\r", "\n")
        for seg in re.split(r"[;；\n]+", text):
            item = str(seg or "").strip(" \t\n;；,，")
            if not item:
                continue
            key = re.sub(r"\s+", "", item).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
    merged = "；".join(out)
    return merged[: max(64, int(limit))]


def _remove_style_ratio_lines(prompt: str) -> str:
    lines: list[str] = []
    for line in str(prompt or "").splitlines():
        text = str(line or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if text.startswith(_STYLE_PREFIXES) or lowered.startswith("style:"):
            continue
        if text.startswith(_RATIO_PREFIXES) or lowered.startswith("ratio:"):
            continue
        lines.append(text)
    return "\n".join(lines).strip()


def normalize_library_prompt(*, prompt: str, style_prompt: str, ratio: str) -> str:
    style_text = str(style_prompt or "").strip() or style_prompt_for_preset(None)
    ratio_norm = normalize_frame_ratio(ratio)
    style_line = f"风格：{style_text}（严格保持一致，不要混合风格）"
    ratio_line = f"画幅：{ratio_norm}"
    body = _remove_style_ratio_lines(prompt)
    if body:
        return f"{style_line}\n{ratio_line}\n{body}".strip()
    return f"{style_line}\n{ratio_line}".strip()


def _apply_role_focus(*, entity_type: str, role: str, descriptor: str) -> str:
    text = str(descriptor or "").strip()
    if str(entity_type or "").strip().lower() != "character":
        return text

    view = _character_view_from_role(role)
    if view == "side":
        return _merge_unique_segments(
            text,
            "构图建议：侧面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。",
            "视角约束：侧面视角突出侧脸轮廓、鼻梁线、下颌线与服装侧面结构。",
            "一致性要求：与该角色正面设定保持同一人特征（发型、服饰、体态、配色）。",
            _CHARACTER_BG_REQUIREMENT,
            limit=1600,
        )
    if view == "back":
        return _merge_unique_segments(
            text,
            "构图建议：背面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。",
            "视角约束：背面视角突出后脑发型轮廓、肩背线条与服装背部结构，不出现完整正脸。",
            "一致性要求：与该角色正面/侧面设定保持同一人特征（发型、服饰、体态、配色）。",
            _CHARACTER_BG_REQUIREMENT,
            limit=1600,
        )
    if view == "bust_front":
        return _merge_unique_segments(
            text,
            "构图建议：正面半身单人角色肖像（胸像到腰部），面部占主导并保留肩颈与上半身服装结构。",
            "视角约束：避免纯头部裁切，保留领口、肩颈与上半身关键服装结构。",
            "一致性要求：与该角色全身正面设定保持同一人特征（五官、发型、服饰、配色）。",
            _CHARACTER_BG_REQUIREMENT,
            limit=1600,
        )
    if view == "bust_three_quarter":
        return _merge_unique_segments(
            text,
            "构图建议：3/4正面半身单人角色肖像（胸像到腰部），面部主导并保留肩颈与上半身服装结构。",
            "视角约束：突出侧脸轮廓、鼻梁线、下颌线，避免完全正脸或纯背面。",
            "一致性要求：与该角色半身正面/全身侧面设定保持同一人特征（发型、五官、服饰、配色）。",
            _CHARACTER_BG_REQUIREMENT,
            limit=1600,
        )
    if view == "bust_side":
        return _merge_unique_segments(
            text,
            "构图建议：侧面半身单人角色肖像（胸像到腰部），突出侧脸轮廓并保留肩颈与上半身服装结构。",
            "视角约束：侧面视角突出鼻梁线、下颌线、耳侧发丝走向，避免正脸占主导。",
            "一致性要求：与该角色半身3/4/全身侧面设定保持同一人特征（发型、服饰、体态、配色）。",
            _CHARACTER_BG_REQUIREMENT,
            limit=1600,
        )
    if view == "front":
        return _merge_unique_segments(
            text,
            "构图建议：正面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。",
            "一致性要求：强调角色身份锚点（发型、五官、服饰、配件）。",
            _CHARACTER_BG_REQUIREMENT,
            limit=1600,
        )
    return text


def _augment_character_prompt(prompt: str, role: str) -> str:
    text = str(prompt or "").strip()
    prefix = str(role or "").strip().split(":", 1)[0]
    if prefix not in _CHARACTER_ROLE_PREFIXES:
        return text

    hints = [
        _character_compose_line(_character_view_from_role(role)),
        _CHARACTER_BACKGROUND_LINE,
        _character_consistency_line(_character_view_from_role(role)),
    ]

    return _append_unique_hints(text, hints)


def _llm_refine_descriptor(
    *,
    entity_type: str,
    name: str,
    role: str,
    source_text: str,
    style_preset: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    system = (
        "你是资深影视概念设计提示词工程师。"
        "请将输入素材整理为可直接用于图像生成的主体描述。"
        "只写可见信息，不要编造，不要输出 Markdown。"
        "输出 JSON：{\"descriptor\":\"...\"}"
    )
    user = (
        f"实体类型：{entity_type}\n"
        f"实体名称：{name}\n"
        f"素材角色：{role or 'default'}\n"
        f"风格预设：{style_preset}\n"
        "原始描述：\n"
        f"{source_text[:2600]}"
    )
    content = chat_completions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout_s=int(timeout_s),
        temperature=0.2,
    )
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    descriptor = obj.get("descriptor")
    if not isinstance(descriptor, str) or not descriptor.strip():
        return None
    return descriptor.strip()[:700], {"llm_model": model}


def _llm_refine_character_identity_anchor(
    *,
    name: str,
    role: str,
    descriptor: str,
    anchor_candidates: list[str],
    style_preset: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not anchor_candidates:
        return None
    view = _character_view_from_role(role)
    joined_candidates = "\n".join(f"{idx + 1}. {item}" for idx, item in enumerate(anchor_candidates[:12]))
    system = (
        "你是图像生成提示词专家。"
        "请把角色身份锚点候选整理为更适合生图的一致性描述。"
        "只允许使用输入中已有信息，不可补充未给出的设定。"
        "视角规则：背面视角不保留正脸细节（瞳色、鼻唇、完整表情）；侧向视角（侧面/半身侧面）优先轮廓线与侧面可见结构。"
        "避免风格词、背景词、镜头词和安全约束词。"
        "输出 JSON：{\"identity_anchor\":\"...\"}。"
        "identity_anchor 用中文分号连接 4-8 个短语。"
    )
    user = (
        f"角色名：{name or '未命名角色'}\n"
        f"视角：{view}\n"
        f"风格预设：{style_preset}\n"
        "当前角色descriptor：\n"
        f"{str(descriptor or '').strip()[:2400]}\n\n"
        "锚点候选（需重写后输出）：\n"
        f"{joined_candidates}"
    )
    content = chat_completions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout_s=int(timeout_s),
        temperature=0.2,
    )
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    value = obj.get("identity_anchor")
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = _filter_identity_anchor_by_view(value, view)
    normalized = _limit_identity_anchor_by_view(normalized, view)
    if not normalized:
        return None
    return normalized, {"identity_anchor_llm_model": model}


