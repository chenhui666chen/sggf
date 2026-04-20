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

def _sanitize_character_descriptor(text: str) -> str:
    raw = str(text or "").replace("\r", "\n")
    if not raw.strip():
        return ""
    segments = [s.strip(" \t\n；;，,、。.") for s in re.split(r"[；;、\n]+", raw) if s.strip()]
    skip_keywords = (
        "风格",
        "画幅",
        "构图",
        "背景",
        "一致性要求",
        "约束",
        "要求",
        "视角",
        "水印",
        "logo",
        "边框",
        "拼贴",
        "全身立绘",
        "单人角色",
        "灰色背景板",
        "纯灰",
    )
    skip_style_tokens = (
        "赛璐璐",
        "二次元",
        "日式动画",
        "高对比度边缘",
        "统一画风",
        "色彩明快",
        "线条清晰",
        "光影柔和统一",
    )
    out: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        candidate = _strip_descriptor_inline_prefix(seg)
        if not candidate:
            continue
        if _is_generic_visual_fragment(candidate):
            continue
        lowered = candidate.lower()
        if any(token in seg for token in skip_keywords):
            continue
        if any(token in seg for token in skip_style_tokens):
            continue
        if _segment_is_non_visual_story(candidate):
            continue
        key = _normalize_prompt_key(lowered)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return "；".join(out).strip()


def _is_sparse_character_descriptor(text: str) -> bool:
    cleaned = _sanitize_character_descriptor(text)
    if not cleaned:
        return True
    segments = [s.strip(" \t\n；;，,、。.") for s in re.split(r"[；;、\n]+", cleaned) if s.strip()]

    # Rich descriptors may be written as one long sentence with comma separators.
    # Use global visual-category hits to avoid false sparse classification.
    visual_groups = (
        ("发", "发型", "短发", "长发", "刘海"),
        ("瞳", "眼", "眉", "脸", "面部", "鼻", "唇", "下颌", "颧骨"),
        ("身材", "体型", "姿态", "站姿", "肩", "背"),
        ("服", "衣", "装", "外套", "内衬", "制服", "袍", "裤", "鞋"),
        ("配件", "耳麦", "徽章", "眼镜", "项链", "戒指", "皮带", "怀表", "机械表"),
        ("色", "配色", "主色"),
        ("表情", "神情", "目光"),
    )
    visual_group_hits = sum(1 for group in visual_groups if any(token in cleaned for token in group))
    if len(cleaned) >= 36 and visual_group_hits >= 4:
        return False

    if len(segments) <= 2:
        return True
    visual_tokens = (
        "发",
        "瞳",
        "眉",
        "脸",
        "面部",
        "鼻",
        "唇",
        "眼",
        "身材",
        "体型",
        "姿态",
        "站姿",
        "服",
        "衣",
        "装",
        "外套",
        "配件",
        "耳麦",
        "徽章",
        "表情",
        "发型",
        "服饰",
    )
    visual_hits = sum(1 for seg in segments if any(token in seg for token in visual_tokens))
    if visual_hits <= 1:
        return True
    if len(cleaned) < 42 and visual_hits < 3:
        return True
    return False


def _deterministic_enrich_sparse_character_descriptor(text: str) -> str:
    base = _sanitize_character_descriptor(text)
    defaults = [
        "短发，发丝层次清晰",
        "脸部轮廓清晰，瞳孔特征明确",
        "上半身职业装版型，主色深灰，配色克制",
        "胸前或肩部有功能配件，位置固定",
        "中等身材，站姿稳定，重心自然",
        "表情沉稳专注，情绪收敛",
    ]
    merged = _merge_unique_segments(base, "；".join(defaults), limit=700)
    return _sanitize_character_descriptor(merged) or merged


def _llm_enrich_sparse_character_descriptor(
    *,
    name: str,
    role: str,
    descriptor: str,
    style_preset: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    source = str(descriptor or "").strip()
    if not source:
        return None
    view = _character_view_from_role(role)
    system = (
        "你是角色设定与生图提示词专家。"
        "任务：当输入描述缺少可视化信息时，补全可直接生图的人物外观设定。"
        "补全维度至少包含：发型、脸型与瞳色、服装版型与主配色、配件位置、体型姿态、表情。"
        "允许基于角色身份与名称做合理默认补全，保证自洽一致。"
        "若视角为侧面，优先补侧脸轮廓与服装侧面可见结构；"
        "若视角为背面，优先补后脑发型、后颈线、肩背轮廓与服装背部可见结构，不输出完整正脸细节。"
        "禁止输出背景、镜头、风格、水印约束；不要输出剧情任务描述。"
        "输出严格 JSON：{\"descriptor\":\"...\"}，用中文分号连接短语。"
    )
    user = (
        f"角色名：{name or '未命名角色'}\n"
        f"视角：{view}\n"
        f"风格预设：{style_preset}\n"
        "原始人物设定：\n"
        f"{source[:2200]}"
    )
    content = chat_completions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout_s=int(timeout_s),
        temperature=0.25,
    )
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    value = obj.get("descriptor")
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = _sanitize_character_descriptor(value.strip())
    if not normalized:
        return None
    return normalized[:700], {"descriptor_enrich_llm_model": model}


def _extract_character_anchor_candidates(text: str) -> list[str]:
    raw = str(text or "").replace("\r", "\n")
    if not raw.strip():
        return []

    skip_prefix = {
        "角色",
        "风格",
        "画幅",
        "比例",
        "构图",
        "背景",
        "背景要求",
        "背景约束",
        "一致性要求",
        "约束",
        "要求",
        "视角",
    }
    skip_keywords = (
        "纯灰色背景板",
        "背景完全干净",
        "无文字",
        "无水印",
        "无logo",
        "无边框",
        "无拼贴",
        "全身",
        "入镜",
        "裁切",
        "赛璐璐",
        "二次元",
        "日式动画",
        "高对比度边缘",
        "统一画风",
        "线条清晰",
        "色彩明快",
        "光影柔和",
    )

    out: list[str] = []
    seen: set[str] = set()
    for raw_line in raw.split("\n"):
        line = str(raw_line or "").strip()
        if not line:
            continue
        head, tail = _split_prefixed_line(line)
        if head in skip_prefix:
            continue
        source = tail if head in {"人物设定", "角色设定", "设定", "描述"} and tail else line
        for seg in re.split(r"[；;。.!！？\n]+", source):
            item = _strip_descriptor_inline_prefix(seg)
            if not item:
                continue
            lowered = item.lower()
            if any(token in item for token in skip_keywords):
                continue
            if any(token in lowered for token in ("style", "ratio", "background", "watermark", "logo")):
                continue
            if _segment_is_non_visual_story(item):
                continue
            key = _normalize_prompt_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= 12:
                return out
    return out


def _llm_filter_character_anchor_candidates(
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
) -> Optional[Tuple[list[str], Dict[str, Any]]]:
    if not anchor_candidates:
        return None
    view = _character_view_from_role(role)
    joined_candidates = "\n".join(f"{idx + 1}. {item}" for idx, item in enumerate(anchor_candidates[:16]))
    system = (
        "你是图像提示词审校专家。"
        "任务：从候选项中筛选“可直接用于角色身份一致性”的可视化锚点。"
        "只保留可见外观要素：发型/五官/体型/服饰/配件/稳定表情。"
        "视角规则：背面视角剔除正脸细节（瞳色、鼻唇、完整表情等）；侧面视角优先轮廓线与侧面可见配件。"
        "必须剔除行为、剧情、任务、关系、抽象能力、场景与风格词。"
        "不可新增输入中没有的信息。"
        "输出严格 JSON：{\"anchor_candidates\":[\"...\"],\"drop_reasons\":[\"...\"]}。"
        "anchor_candidates 保留 4-8 条短语。"
    )
    user = (
        f"角色名：{name or '未命名角色'}\n"
        f"视角：{view}\n"
        f"风格预设：{style_preset}\n"
        "角色描述：\n"
        f"{str(descriptor or '').strip()[:2200]}\n\n"
        "候选锚点：\n"
        f"{joined_candidates}"
    )
    content = chat_completions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout_s=int(timeout_s),
        temperature=0.1,
    )
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    out_raw = obj.get("anchor_candidates")
    if not isinstance(out_raw, list):
        return None
    filtered: list[str] = []
    seen: set[str] = set()
    for item in out_raw:
        if not isinstance(item, str) or not item.strip():
            continue
        normalized = _filter_identity_anchor_by_view(item, view)
        if not normalized:
            continue
        for seg in re.split(r"[；;，,\n]+", normalized):
            part = str(seg or "").strip(" \t\n；;，,。.")
            key = _normalize_prompt_key(part)
            if not part or not key or key in seen:
                continue
            seen.add(key)
            filtered.append(part)
            if len(filtered) >= 8:
                break
        if len(filtered) >= 8:
            break
    if not filtered:
        return None
    merged = _limit_identity_anchor_by_view("；".join(filtered), view)
    if not merged:
        return None
    out = [s.strip() for s in re.split(r"[；;]+", merged) if s.strip()]
    return out[:8], {"identity_anchor_filter_llm_model": model}


def _deterministic_filter_character_anchor_candidates(
    anchor_candidates: list[str], limit: int = 8, view: str = "default"
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in anchor_candidates:
        item = str(raw or "").strip()
        if not item:
            continue
        normalized = _filter_identity_anchor_by_view(item, view)
        if not normalized:
            continue
        for seg in re.split(r"[；;，,\n]+", normalized):
            part = str(seg or "").strip(" \t\n；;，,。.")
            key = _normalize_prompt_key(part)
            if _segment_conflicts_view_visibility(part, view):
                continue
            if not part or not key or key in seen:
                continue
            seen.add(key)
            out.append(part)
            if len(out) >= max(1, int(limit)):
                return out
    return out


def _finalize_identity_anchor_text(identity_anchor: str, fallback_candidates: list[str], view: str) -> tuple[str, str]:
    audited = _filter_identity_anchor_by_view(identity_anchor, view)
    audited = _limit_identity_anchor_by_view(audited, view)
    if audited:
        return audited, "llm_anchor"

    deterministic_limit = 6 if view in {"side", "back", "bust_three_quarter", "bust_side"} else 8
    deterministic = _deterministic_filter_character_anchor_candidates(
        fallback_candidates,
        limit=deterministic_limit,
        view=view,
    )
    if deterministic:
        merged = _limit_identity_anchor_by_view(_normalize_identity_anchor_text("；".join(deterministic)), view)
        if merged:
            return merged, "deterministic_fallback"
    return "", "empty"


def _append_unique_hints(text: str, hints: list[str]) -> str:
    merged = str(text or "").strip()
    if not merged:
        return merged
    existing_key = _normalize_prompt_key(merged)
    for hint in hints:
        hint_text = str(hint or "").strip()
        if not hint_text:
            continue
        hint_key = _normalize_prompt_key(hint_text)
        if hint_key and hint_key in existing_key:
            continue
        merged = f"{merged}\n{hint_text}"
        existing_key = _normalize_prompt_key(merged)
    return merged.strip()


def _clean_character_prompt_conflicts(*, prompt: str, role: str) -> str:
    text = str(prompt or "").replace("\r\n", "\n").strip()
    prefix = str(role or "").strip().split(":", 1)[0]
    if prefix not in _CHARACTER_ROLE_PREFIXES:
        return text
    if not text:
        return text
    target_view = _character_view_from_role(role)

    # Remove legacy English constraints to keep a single Chinese prompt style.
    text = re.sub(
        r"(?im)^\s*Full-body character sheet,.*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*Single character only,.*$",
        "",
        text,
    )
    text = re.sub(
        r"(?im)^\s*(Front|Side|Back) view full body,.*$",
        "",
        text,
    )

    drop_patterns = (
        re.compile(r"头肩", re.IGNORECASE),
        re.compile(r"角色占画面\s*\d+\s*%\s*[-~～至到]\s*\d+\s*%", re.IGNORECASE),
        re.compile(r"保留额头到下颌完整轮廓", re.IGNORECASE),
    )

    def _clean_segment(seg: str) -> str:
        item = str(seg or "").strip()
        if not item:
            return ""
        item = re.sub(r"正面\s*或\s*(?:3\s*/\s*4|四分之三|三分之二)\s*正面", "正面", item, flags=re.IGNORECASE)
        if target_view in {"bust_front", "bust_three_quarter", "bust_side"}:
            item = item.replace("单人角色立绘/肖像", "单人角色半身肖像")
            item = item.replace("立绘/肖像", "半身肖像")
            item = item.replace("单人肖像", "单人半身肖像")
            item = item.replace("全身立绘", "半身肖像")
        else:
            item = item.replace("单人角色立绘/肖像", "单人角色全身立绘")
            item = item.replace("立绘/肖像", "全身立绘")
            item = item.replace("单人肖像", "单人全身立绘")
        item = item.replace("背景细节丰富", "纯灰色背景板，背景完全干净")
        item = item.replace("背景干净简洁", "纯灰色背景板，背景完全干净")
        item = item.replace("背景干净", "纯灰色背景板，背景完全干净")
        # 强制移除具象场景背景，统一为纯灰色背景板。
        if re.search(r"(?:^|[；;，,])\s*背景(?:为|是|：|:)", item) and ("灰色背景板" not in item and "纯灰" not in item):
            return _CHARACTER_BG_REQUIREMENT
        item = re.sub(r"\s+", " ", item).strip(" ;；，,")
        for pat in drop_patterns:
            if pat.search(item):
                return ""
        if re.search(r"肖像构图", item, flags=re.IGNORECASE):
            return ""
        return item

    out_lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.split("\n"):
        line = str(raw_line or "").strip()
        if not line:
            continue
        if "：" in line:
            head, tail = line.split("：", 1)
            segments = [s.strip() for s in re.split(r"[；;]+", tail) if s.strip()]
            cleaned: list[str] = []
            for seg in segments:
                value = _clean_segment(seg)
                key = _normalize_prompt_key(value)
                if not value or not key or key in seen:
                    continue
                seen.add(key)
                cleaned.append(value)
            if cleaned:
                out_lines.append(f"{head.strip()}：" + "；".join(cleaned))
            continue

        value = _clean_segment(line)
        key = _normalize_prompt_key(value)
        if not value or not key or key in seen:
            continue
        seen.add(key)
        out_lines.append(value)

    cleaned_text = "\n".join(out_lines).strip()
    if cleaned_text:
        cleaned_text = _append_unique_hints(cleaned_text, [_CHARACTER_BG_REQUIREMENT])
    return cleaned_text


def _canonicalize_character_prompt(
    *,
    prompt: str,
    role: str,
    style_prompt: str,
    ratio: str,
    name: str,
    identity_anchor: str = "",
) -> str:
    text = str(prompt or "").strip()
    prefix = str(role or "").strip().split(":", 1)[0]
    if prefix not in _CHARACTER_ROLE_PREFIXES:
        return text

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    style_val = _extract_prefixed_value(lines, ("风格", "style"))
    ratio_val = _extract_prefixed_value(lines, ("画幅", "比例", "ratio"))
    descriptor_raw = _extract_prefixed_value(lines, ("人物设定",))

    if not descriptor_raw:
        for line in lines:
            head, _tail = _split_prefixed_line(line)
            if head in {
                "风格",
                "style",
                "画幅",
                "比例",
                "ratio",
                "角色",
                "构图",
                "构图建议",
                "构图约束",
                "背景",
                "背景要求",
                "背景约束",
                "一致性要求",
                "约束",
                "要求",
                "主体约束",
                "视角",
                "视角约束",
            }:
                continue
            descriptor_raw = _merge_unique_segments(descriptor_raw, line, limit=900)

    descriptor = _sanitize_character_descriptor(descriptor_raw)
    if not descriptor:
        descriptor = _sanitize_character_descriptor(text)
    if not descriptor:
        descriptor = "角色外观与服装特征清晰可辨。"

    style_clean = _sanitize_style_text(style_val) or _sanitize_style_text(style_prompt) or style_prompt_for_preset(None)
    ratio_clean = normalize_frame_ratio(ratio_val or ratio)
    view = _character_view_from_role(role)
    descriptor_view = _adapt_character_descriptor_for_view(descriptor, view) or descriptor

    return "\n".join(
        [
            f"人物设定：{descriptor_view}",
            _character_compose_line(view),
            f"风格：{style_clean}（严格保持一致，不要混合风格）",
            f"画幅：{ratio_clean}",
            _CHARACTER_BACKGROUND_LINE,
            _character_consistency_line(view, identity_anchor=identity_anchor),
            _CHARACTER_CONSTRAINT_LINE,
        ]
    ).strip()


