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


