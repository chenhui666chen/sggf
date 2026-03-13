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

_STYLE_PREFIXES = ("风格：", "风格:", "style:")
_RATIO_PREFIXES = ("画幅：", "画幅:", "比例：", "比例:", "ratio:")
_CHARACTER_BG_REQUIREMENT = "背景要求：纯灰色背景板，背景完全干净，无场景元素、无杂物、无文字、无多余人物。"
_CHARACTER_BACKGROUND_LINE = "背景：纯灰色背景板，背景完全干净，无场景元素、无杂物、无文字、无多余人物。"
_CHARACTER_CONSTRAINT_LINE = "约束：无文字，无水印，无logo，无边框，无拼贴。"
_CHARACTER_ROLE_PREFIXES = {
    "lib_character_portrait",
    "lib_character_portrait_side",
    "lib_character_portrait_back",
    "lib_character_portrait_bust",
    "lib_character_portrait_bust_three_quarter",
    "lib_character_portrait_bust_side",
}


def _is_placeholder_name(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if re.fullmatch(r"[?？\s]+", value):
        return True
    lowered = value.lower()
    if lowered in {"unknown", "n/a", "na"}:
        return True
    if value in {"未知", "未命名", "角色", "人物", "角色名"}:
        return True
    return False


def _is_generic_visual_fragment(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return True
    normalized = re.sub(r"[（）()\[\]【】\s，,。.;；:：]+", "", raw)
    if not normalized:
        return True
    generic_terms = {
        "发型",
        "五官",
        "服饰",
        "配件",
        "体态",
        "配色",
        "体型",
        "姿态",
        "人物",
        "角色",
        "特征",
        "识别特征",
        "稳定识别",
        "保持一致",
    }
    return normalized in generic_terms


def _character_compose_line(view: str) -> str:
    if view == "side":
        return "构图：侧面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切；严格侧面全身视角（接近90°侧身），避免正脸占主导，突出侧脸轮廓与服装侧面结构。"
    if view == "back":
        return "构图：背面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切；严格背面全身视角（背身），不出现完整正脸，突出后脑发型、肩背轮廓与服装背部结构。"
    if view == "bust_front":
        return "构图：正面半身单人角色肖像（胸像到腰部），面部主导并保留肩颈与上半身服装结构，避免纯头部裁切。"
    if view == "bust_three_quarter":
        return "构图：3/4正面半身单人角色肖像（胸像到腰部），面部主导并清晰呈现侧脸轮廓、肩颈与上半身服装结构。"
    if view == "bust_side":
        return "构图：侧面半身单人角色肖像（胸像到腰部），突出侧脸轮廓并保留肩颈与上半身服装结构，避免正脸占主导。"
    return "构图：正面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切；正面全身视角，五官与服装正面结构清晰可辨。"


def _is_front_face_semantic(seg: str) -> bool:
    text = str(seg or "").strip()
    if not text:
        return False
    face_tokens = (
        "瞳",
        "眼",
        "眉",
        "鼻",
        "唇",
        "嘴",
        "脸部",
        "脸型",
        "方脸",
        "圆脸",
        "面部",
        "下颌",
        "颧骨",
        "法令纹",
        "正脸",
        "正面视角",
        "表情",
        "神情",
        "微笑",
        "浅笑",
        "目光",
    )
    return any(token in text for token in face_tokens)


def _is_front_only_body_semantic(seg: str) -> bool:
    text = str(seg or "").strip()
    if not text:
        return False
    body_tokens = (
        "胸前",
        "胸口",
        "左胸",
        "右胸",
        "前襟",
        "领带",
        "领结",
        "正面徽章",
        "胸章",
        "胸针",
        "胸牌",
        "前胸",
    )
    return any(token in text for token in body_tokens)


def _segment_conflicts_view_visibility(seg: str, view: str) -> bool:
    text = str(seg or "").strip()
    if not text:
        return False
    if view == "back":
        if _is_front_face_semantic(text) or _is_front_only_body_semantic(text):
            return True
        if any(token in text for token in ("正面", "正脸", "面向镜头", "直视镜头", "目视镜头")):
            return True
    if view in {"side", "bust_side"}:
        if any(token in text for token in ("正面", "正脸", "面向镜头", "直视镜头", "目视镜头")):
            return True
    return False


def _limit_identity_anchor_by_view(identity_anchor: str, view: str) -> str:
    text = str(identity_anchor or "").strip()
    if not text:
        return ""
    limit = 6 if view in {"side", "back", "bust_three_quarter", "bust_side"} else 8
    segments = [s.strip(" \t\n；;，,。.") for s in re.split(r"[；;，,\n]+", text) if s.strip()]
    if not segments:
        return ""
    return "；".join(segments[:limit])


def _adapt_character_descriptor_for_view(text: str, view: str) -> str:
    cleaned = _sanitize_character_descriptor(text)
    if not cleaned:
        return ""
    segments = [s.strip(" \t\n；;，,、。.") for s in re.split(r"[；;、]+", cleaned) if s.strip()]
    kept: list[str] = []
    for seg in segments:
        item = str(seg or "").strip()
        if not item:
            continue
        if _segment_conflicts_view_visibility(item, view):
            continue
        kept.append(item)

    if view == "side":
        kept.append("侧脸轮廓清晰，鼻梁线与下颌线可辨，耳侧与发丝走向明确")
    elif view == "back":
        kept.append("后脑发型轮廓与后颈线清晰，肩背线条与服装背部结构明确")
    elif view == "bust_front":
        kept.append("面部主导且肩颈结构清晰，上半身服装关键细节可辨")
    elif view == "bust_three_quarter":
        kept.append("3/4半身视角下侧脸轮廓清晰，肩颈与上半身服装结构完整")
    elif view == "bust_side":
        kept.append("侧面半身轮廓清晰，耳侧发丝走向与肩颈服装结构明确")

    return _merge_unique_segments("；".join(kept), limit=900)


def _normalize_identity_anchor_text(text: str) -> str:
    raw = str(text or "").replace("\r", "\n").strip()
    if not raw:
        return ""
    parts = [seg.strip(" \t\n；;，,、。.") for seg in re.split(r"[；;，,、\n]+", raw) if seg.strip()]
    if not parts:
        return ""

    # Keep only visible identity anchors; filter out style/composition/background/safety noise.
    drop_keywords = (
        "风格",
        "画幅",
        "构图",
        "背景",
        "一致性要求",
        "约束",
        "水印",
        "logo",
        "边框",
        "拼贴",
        "纯灰",
        "灰色背景板",
        "全身",
        "镜头",
        "光线",
        "灯光",
        "anime",
        "style",
        "ratio",
        "watermark",
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
    weak_non_visual_tokens = (
        "位置固定",
        "重心自然",
        "清晰可辨",
        "结构明确",
        "特征明确",
        "稳定可识别",
        "保持一致",
    )
    for part in parts:
        lowered = part.lower()
        if any(token in part for token in drop_keywords) or any(token in lowered for token in drop_keywords):
            continue
        if _segment_is_non_visual_story(part):
            continue
        if _is_generic_visual_fragment(part):
            continue
        if (len(part) <= 4) and (not _segment_has_visual_cues(part)):
            continue
        if any(token in part for token in weak_non_visual_tokens) and (not _segment_has_visual_cues(part)):
            continue
        key = _normalize_prompt_key(part)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(part)
        if len(out) >= 8:
            break
    if not out:
        return ""
    return "；".join(out)[:260]


def _remove_non_visual_anchor_segments(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    behavior_keywords = (
        "发现",
        "协助",
        "部署",
        "调查",
        "执行",
        "追踪",
        "指挥",
        "判断",
        "分析",
        "潜入",
        "攻击",
        "防御",
        "回忆",
        "思考",
        "保护",
        "拯救",
        "参与",
        "完成",
        "处理",
        "侦查",
    )
    keep: list[str] = []
    for seg in re.split(r"[；;，,、\n]+", raw):
        item = str(seg or "").strip(" \t\n；;，,、。.")
        if not item:
            continue
        if any(token in item for token in behavior_keywords):
            continue
        keep.append(item)
    if not keep:
        return ""
    return "；".join(keep)


def _filter_identity_anchor_by_view(identity_anchor: str, view: str) -> str:
    normalized = _normalize_identity_anchor_text(_remove_non_visual_anchor_segments(identity_anchor))
    if not normalized:
        return ""
    segments = [s.strip(" \t\n；;，,、。.") for s in re.split(r"[；;、]+", normalized) if s.strip()]
    out: list[str] = []
    for seg in segments:
        if _segment_conflicts_view_visibility(seg, view):
            continue
        out.append(seg)
    filtered = _normalize_identity_anchor_text("；".join(out))
    return _limit_identity_anchor_by_view(filtered, view)


def _character_consistency_line(view: str, identity_anchor: str = "") -> str:
    anchor_text = _filter_identity_anchor_by_view(identity_anchor, view)
    if view == "bust_front":
        if anchor_text:
            return f"一致性要求：与全身正面图保持同一角色身份锚点（{anchor_text}）。"
        return "一致性要求：与全身正面图保持同一角色身份锚点，重点保持五官、发型、领口与肩颈服装细节一致。"
    if view == "bust_three_quarter":
        if anchor_text:
            return f"一致性要求：与半身正面和全身侧面图保持同一角色身份锚点（{anchor_text}）。"
        return "一致性要求：与半身正面和全身侧面图保持同一角色身份锚点，重点保持侧脸轮廓与上半身服装结构一致。"
    if view == "bust_side":
        if anchor_text:
            return f"一致性要求：与半身3/4和全身侧面图保持同一角色身份锚点（{anchor_text}）。"
        return "一致性要求：与半身3/4和全身侧面图保持同一角色身份锚点，重点保持侧脸轮廓、发型与肩颈服装细节一致。"
    if view == "side":
        if anchor_text:
            return f"一致性要求：与正面图保持同一角色身份锚点（{anchor_text}）。"
        return "一致性要求：与正面图保持同一角色身份锚点，重点保持发型、五官、服饰、配件和体态一致。"
    if view == "back":
        if anchor_text:
            return f"一致性要求：与正面和侧面图保持同一角色身份锚点（{anchor_text}）。"
        return "一致性要求：与正面和侧面图保持同一角色身份锚点，重点保持发型轮廓、服饰版型与配色、配件位置一致。"
    if anchor_text:
        return f"一致性要求：角色身份锚点保持一致（{anchor_text}）。"
    return "一致性要求：角色身份锚点保持一致，突出发型、五官、服饰和配件等特征。"


def _character_view_from_role(role: str) -> str:
    prefix = str(role or "").strip().split(":", 1)[0]
    if prefix == "lib_character_portrait_side":
        return "side"
    if prefix == "lib_character_portrait_back":
        return "back"
    if prefix == "lib_character_portrait_bust":
        return "bust_front"
    if prefix == "lib_character_portrait_bust_three_quarter":
        return "bust_three_quarter"
    if prefix == "lib_character_portrait_bust_side":
        return "bust_side"
    if prefix == "lib_character_portrait":
        return "front"
    return "default"


def _normalize_prompt_key(text: str) -> str:
    lowered = str(text or "").strip().lower()
    return re.sub(r"[\s\u3000,，.。;；:：()（）\[\]【】'\"`~!！?？\-_/\\]+", "", lowered)


def _split_prefixed_line(line: str) -> tuple[str, str]:
    text = str(line or "").strip()
    for sep in ("：", ":"):
        if sep in text:
            head, tail = text.split(sep, 1)
            return head.strip(), tail.strip()
    return text, ""


def _extract_prefixed_value(lines: list[str], prefixes: tuple[str, ...]) -> str:
    for line in lines:
        head, tail = _split_prefixed_line(line)
        if head in prefixes and tail:
            return tail
    return ""


def _sanitize_style_text(style_text: str) -> str:
    text = str(style_text or "").strip()
    if not text:
        return text
    text = re.sub(r"[（(]\s*严格保持一致[^）)]*[）)]\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"[，,]?\s*纯灰色背景板\s*[，,]?\s*背景完全干净", "", text)
    text = re.sub(r"[，,]?\s*纯灰色背景板", "", text)
    text = re.sub(r"[，,]?\s*背景完全干净", "", text)
    text = re.sub(r"[，,]{2,}", "，", text).strip()
    return text.strip("，,。;；")


def _strip_descriptor_inline_prefix(seg: str) -> str:
    text = str(seg or "").strip()
    if not text:
        return ""
    # Remove embedded structural labels from free-form descriptor text.
    text = re.sub(r"^\s*(?:角色|人物设定|角色设定|设定|描述|简介)\s*[：:]\s*", "", text, flags=re.IGNORECASE)
    return text.strip(" \t\n；;，,。.")


def _segment_has_visual_cues(seg: str) -> bool:
    text = str(seg or "").strip()
    if not text:
        return False
    visual_tokens = (
        "发",
        "发型",
        "短发",
        "长发",
        "瞳",
        "眼",
        "眉",
        "脸",
        "面部",
        "鼻",
        "唇",
        "肤",
        "身材",
        "体型",
        "姿态",
        "站姿",
        "服",
        "衣",
        "装",
        "外套",
        "内衬",
        "披风",
        "鞋",
        "手套",
        "配件",
        "耳麦",
        "徽章",
        "眼镜",
        "项链",
        "戒指",
        "皮带",
        "色",
        "配色",
        "表情",
        "神情",
        "纹理",
        "疤",
    )
    return any(token in text for token in visual_tokens)


def _segment_is_non_visual_story(seg: str) -> bool:
    text = str(seg or "").strip()
    if not text:
        return True
    story_tokens = (
        "揭示",
        "真相",
        "同事",
        "母亲",
        "父亲",
        "朋友",
        "导师",
        "敌人",
        "主角",
        "反派",
        "智者",
        "反抗核心",
        "系统篡改记忆",
        "剧情",
        "任务",
        "线索",
        "阴谋",
        "组织",
        "关系",
        "觉醒",
        "能力",
        "成为",
        "揭露",
    )
    if any(token in text for token in story_tokens) and not _segment_has_visual_cues(text):
        return True
    # Bare character name or role label fragment is not useful visual descriptor.
    if len(text) <= 8 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9_·\-\s]+", text) and (not _segment_has_visual_cues(text)):
        return True
    return False


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


def suggest_library_prompt(
    *,
    mode: LibraryPromptMode,
    entity_type: str,
    name: str,
    descriptor: str,
    raw_prompt: str,
    style_preset: str,
    ratio: str,
    style_prompt: Optional[str] = None,
    role: Optional[str] = None,
    enable_anchor_analysis: bool = True,
    enable_descriptor_enrichment: bool = True,
    force_template_rebuild: bool = False,
) -> Tuple[str, str, Dict[str, Any]]:
    preset = normalize_style_preset(style_preset)
    style_text = (style_prompt or "").strip() or style_prompt_for_preset(preset)
    negative_prompt = style_negative_prompt_for_preset(preset)
    ratio_norm = normalize_frame_ratio(ratio)
    entity_type_norm = str(entity_type or "").strip().lower()
    name_norm = str(name or "").strip()
    role_text = str(role or "").strip()
    raw_prompt_text = str(raw_prompt or "").strip()
    raw_prompt_for_merge = "" if bool(force_template_rebuild) else raw_prompt_text

    meta: Dict[str, Any] = {
        "mode": str(mode),
        "style_preset": preset,
        "style_prompt": style_text,
        "ratio": ratio_norm,
        "role": role_text,
        "character_view": _character_view_from_role(role_text),
        "llm_used": False,
        "force_template_rebuild": bool(force_template_rebuild),
    }

    descriptor_source = str(descriptor or "").strip()
    if entity_type_norm == "character" and bool(enable_descriptor_enrichment):
        sparse_input = _is_sparse_character_descriptor(descriptor_source)
        meta["descriptor_sparse_input"] = bool(sparse_input)
        meta["descriptor_enrich_llm_used"] = False
        if sparse_input:
            enable_desc_llm = env_flag("DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_ENABLE_LLM", default=True)
            require_desc_llm = env_flag("DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_REQUIRE_LLM", default=False)
            desc_api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
            desc_base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
            desc_model = pick_model(
                primary_env="DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_MODEL",
                fallback_env="DREAMWEAVER_LIBRARY_PROMPT_MODEL",
                default="qwen-plus",
            )
            desc_timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_TIMEOUT", "90") or "90")

            if enable_desc_llm and desc_api_key and desc_base_url:
                try:
                    enriched_out = _llm_enrich_sparse_character_descriptor(
                        name=name_norm,
                        role=role_text,
                        descriptor=descriptor_source,
                        style_preset=preset,
                        api_key=desc_api_key,
                        base_url=desc_base_url,
                        model=desc_model,
                        timeout_s=desc_timeout_s,
                    )
                    if enriched_out:
                        descriptor_source, desc_meta = enriched_out
                        meta.update({"descriptor_enrich_llm_used": True, **desc_meta})
                    else:
                        meta["descriptor_enrich_reason"] = "invalid_llm_output"
                        if require_desc_llm:
                            raise RuntimeError("character descriptor enrich LLM output invalid")
                except Exception as exc:  # noqa: BLE001
                    meta["descriptor_enrich_llm_error"] = str(exc)
                    if require_desc_llm:
                        raise RuntimeError(f"character descriptor enrich LLM failed: {exc}") from exc
            else:
                if not enable_desc_llm:
                    meta["descriptor_enrich_reason"] = "descriptor_enrich_llm_disabled"
                else:
                    meta["descriptor_enrich_reason"] = "descriptor_enrich_llm_config_missing"
                if require_desc_llm:
                    raise RuntimeError("character descriptor enrich require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

            if not meta.get("descriptor_enrich_llm_used"):
                descriptor_source = _deterministic_enrich_sparse_character_descriptor(descriptor_source)
                meta["descriptor_enrich_fallback"] = "deterministic"
        meta["descriptor_for_prompt"] = descriptor_source

    merged_descriptor = _merge_unique_segments(descriptor_source, raw_prompt_for_merge, limit=1400)
    merged_descriptor = _apply_role_focus(entity_type=entity_type_norm, role=role_text, descriptor=merged_descriptor)

    identity_anchor_text = ""
    if entity_type_norm == "character" and bool(enable_anchor_analysis):
        anchor_source_text = _merge_unique_segments(descriptor_source, raw_prompt_for_merge, limit=1800)
        anchor_candidates = _extract_character_anchor_candidates(anchor_source_text)
        meta["identity_anchor_candidates_raw"] = anchor_candidates[:10]
        meta["identity_anchor_candidate_count_raw"] = len(anchor_candidates)
        meta["identity_anchor_filter_llm_used"] = False
        meta["identity_anchor_llm_used"] = False
        meta["identity_anchor_audit_used"] = False

        if anchor_candidates:
            enable_filter_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_FILTER_ENABLE_LLM", default=True)
            require_filter_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_FILTER_REQUIRE_LLM", default=False)

            enable_anchor_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_ENABLE_LLM", default=True)
            require_anchor_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_REQUIRE_LLM", default=False)
            anchor_api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
            anchor_base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
            filter_model = pick_model(
                primary_env="DREAMWEAVER_LIBRARY_ANCHOR_FILTER_MODEL",
                fallback_env="DREAMWEAVER_LIBRARY_ANCHOR_MODEL",
                default="qwen-plus",
            )
            filter_timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_ANCHOR_FILTER_TIMEOUT", "90") or "90")

            anchor_model = pick_model(
                primary_env="DREAMWEAVER_LIBRARY_ANCHOR_MODEL",
                fallback_env="DREAMWEAVER_LIBRARY_PROMPT_MODEL",
                default="qwen-plus",
            )
            anchor_timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_ANCHOR_TIMEOUT", "90") or "90")

            view_for_anchor = _character_view_from_role(role_text)
            default_anchor_limit = 6 if view_for_anchor in {"side", "back", "bust_three_quarter", "bust_side"} else 8
            anchor_candidates_final = _deterministic_filter_character_anchor_candidates(
                anchor_candidates,
                limit=default_anchor_limit,
                view=view_for_anchor,
            )
            meta["identity_anchor_candidates_det"] = anchor_candidates_final[:8]
            meta["identity_anchor_candidate_count_det"] = len(anchor_candidates_final)
            if enable_filter_llm and anchor_api_key and anchor_base_url:
                try:
                    filter_out = _llm_filter_character_anchor_candidates(
                        name=name_norm,
                        role=role_text,
                        descriptor=anchor_source_text,
                        anchor_candidates=anchor_candidates,
                        style_preset=preset,
                        api_key=anchor_api_key,
                        base_url=anchor_base_url,
                        model=filter_model,
                        timeout_s=filter_timeout_s,
                    )
                    if filter_out:
                        filtered_from_llm, filter_meta = filter_out
                        if filtered_from_llm:
                            anchor_candidates_final = filtered_from_llm
                        meta.update({"identity_anchor_filter_llm_used": True, **filter_meta})
                    else:
                        meta["identity_anchor_filter_reason"] = "invalid_llm_output"
                        if require_filter_llm:
                            raise RuntimeError("character anchor filter LLM output invalid")
                except Exception as exc:  # noqa: BLE001
                    meta["identity_anchor_filter_llm_error"] = str(exc)
                    if require_filter_llm:
                        raise RuntimeError(f"character anchor filter LLM failed: {exc}") from exc
            else:
                if not enable_filter_llm:
                    meta["identity_anchor_filter_reason"] = "filter_llm_disabled"
                else:
                    meta["identity_anchor_filter_reason"] = "filter_llm_config_missing"
                if require_filter_llm:
                    raise RuntimeError("character anchor filter require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

            if not anchor_candidates_final:
                meta["identity_anchor_reason"] = "no_filtered_anchor_candidate"
                if require_anchor_llm:
                    raise RuntimeError("character anchor candidate empty after filter")

            meta["identity_anchor_candidates"] = anchor_candidates_final[:8]
            meta["identity_anchor_candidate_count"] = len(anchor_candidates_final)

            if enable_anchor_llm and anchor_api_key and anchor_base_url:
                try:
                    anchor_out = _llm_refine_character_identity_anchor(
                        name=name_norm,
                        role=role_text,
                        descriptor=anchor_source_text,
                        anchor_candidates=anchor_candidates_final,
                        style_preset=preset,
                        api_key=anchor_api_key,
                        base_url=anchor_base_url,
                        model=anchor_model,
                        timeout_s=anchor_timeout_s,
                    )
                    if anchor_out:
                        identity_anchor_text, anchor_meta = anchor_out
                        meta.update({"identity_anchor_llm_used": True, **anchor_meta})
                        meta["identity_anchor"] = identity_anchor_text
                    else:
                        meta["identity_anchor_reason"] = "invalid_llm_output"
                        if require_anchor_llm:
                            raise RuntimeError("character anchor LLM output invalid")
                except Exception as exc:  # noqa: BLE001
                    meta["identity_anchor_llm_error"] = str(exc)
                    if require_anchor_llm:
                        raise RuntimeError(f"character anchor LLM failed: {exc}") from exc
            else:
                if not enable_anchor_llm:
                    meta["identity_anchor_reason"] = "anchor_llm_disabled"
                else:
                    meta["identity_anchor_reason"] = "anchor_llm_config_missing"
                if require_anchor_llm:
                    raise RuntimeError("character anchor require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

            # Final deterministic audit: normalize and strip non-visual semantics.
            identity_anchor_text, anchor_audit_source = _finalize_identity_anchor_text(
                identity_anchor_text,
                anchor_candidates_final,
                view_for_anchor,
            )
            meta["identity_anchor_audit_used"] = True
            meta["identity_anchor_audit_source"] = anchor_audit_source
            if identity_anchor_text:
                meta["identity_anchor"] = identity_anchor_text
            elif not str(meta.get("identity_anchor_reason") or "").strip():
                meta["identity_anchor_reason"] = "no_valid_anchor_after_audit"
        else:
            meta["identity_anchor_reason"] = "no_anchor_candidate"
    elif entity_type_norm == "character":
        meta["identity_anchor_reason"] = "anchor_analysis_disabled"

    final_descriptor = merged_descriptor
    if mode == "ai":
        enable_llm = env_flag("DREAMWEAVER_LIBRARY_PROMPT_ENABLE_LLM", default=True)
        require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag("DREAMWEAVER_LIBRARY_PROMPT_REQUIRE_LLM", default=False)
        api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
        base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
        model = pick_model(primary_env="DREAMWEAVER_LIBRARY_PROMPT_MODEL", fallback_env="DREAMWEAVER_SCRIPT_MODEL", default="qwen-plus")
        timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_PROMPT_TIMEOUT", "120") or "120")
        if enable_llm and api_key and base_url:
            try:
                out = _llm_refine_descriptor(
                    entity_type=entity_type_norm,
                    name=name_norm,
                    role=role_text,
                    source_text=merged_descriptor,
                    style_preset=preset,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    timeout_s=timeout_s,
                )
                if out:
                    final_descriptor, llm_meta = out
                    final_descriptor = _apply_role_focus(entity_type=entity_type_norm, role=role_text, descriptor=final_descriptor)
                    meta.update({"llm_used": True, **llm_meta})
                else:
                    meta["llm_reason"] = "invalid_llm_output"
            except Exception as exc:  # noqa: BLE001
                meta["llm_error"] = str(exc)
                if require_llm:
                    raise RuntimeError(f"library prompt LLM failed: {exc}") from exc
        elif require_llm:
            raise RuntimeError("library prompt require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

    if mode == "template" and raw_prompt_text and (not bool(force_template_rebuild)):
        prompt = normalize_library_prompt(prompt=raw_prompt_text, style_prompt=style_text, ratio=ratio_norm)
    else:
        prompt = build_library_prompt(
            entity_type=entity_type_norm,
            name=name_norm,
            descriptor=final_descriptor,
            style_prompt=style_text,
            ratio=ratio_norm,
        )
        prompt = normalize_library_prompt(prompt=prompt, style_prompt=style_text, ratio=ratio_norm)

    prompt = _clean_character_prompt_conflicts(prompt=prompt, role=role_text)
    prompt = _canonicalize_character_prompt(
        prompt=prompt,
        role=role_text,
        style_prompt=style_text,
        ratio=ratio_norm,
        name=name_norm,
        identity_anchor=identity_anchor_text,
    )
    return prompt, negative_prompt, meta
