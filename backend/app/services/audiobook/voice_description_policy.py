"""Voice description quality rules and selected-voice guardrails."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from app.schemas.voice_tags import VOICE_TAG_LABELS
from app.services.audiobook.tts_model_ids import DEFAULT_AUDIOBOOK_TTS_MODEL
from app.services.audiobook.voice_catalog import get_voice_entry


@dataclass(frozen=True)
class VoiceDescriptionResult:
    """Normalized voice description plus any soft corrections applied."""

    description: str
    warnings: List[str] = field(default_factory=list)


_GENDER_LABELS = {
    "male": "男性",
    "female": "女性",
    "neutral": "中性",
}

_STYLE_TRAITS = {
    "calm": ["沉稳", "平和"],
    "clear": ["清晰", "圆润"],
    "cute": ["稚嫩", "甜美"],
    "elder": ["苍老", "沉稳"],
    "elegant": ["知性", "圆润"],
    "energetic": ["明亮", "有活力"],
    "gentle": ["温柔", "亲切自然"],
    "magnetic": ["沙哑", "有磁性"],
    "powerful": ["有力", "吐字清晰"],
    "soothing": ["舒缓", "温和"],
    "warm": ["温暖", "有活力"],
}

_PITCH_BY_STYLE = {
    "calm": "偏低",
    "clear": "中音",
    "cute": "偏高",
    "elder": "偏低",
    "elegant": "中音",
    "energetic": "偏高",
    "gentle": "中音",
    "magnetic": "偏低",
    "powerful": "中低音",
    "soothing": "中低音",
    "warm": "中音",
}

# 年龄冲突判据直接取标签词表的中文展示名，避免第二张中文年龄表与画像投影漂移。
_AGE_PROFILE_TOKENS = tuple(
    dict.fromkeys(label["zh"] for label in VOICE_TAG_LABELS["age_impression"].values())
)

_VAGUE_TERMS = ("好听", "普通", "高级", "最喜欢")
_IMITATION_TERMS = ("模仿", "像某", "明星", "演员", "原声")
_DESCRIPTION_FIELD_NAMES = ("性别", "年龄感", "音调", "语速", "情绪", "特点", "用途")
_NARRATION_USE_CASE_TERMS = ("旁白", "解说", "播报", "纪录片")
_TIMBRE_CONFLICT_RULES = (
    (
        ("稚嫩", "甜美"),
        ("沙哑", "烟嗓", "苍老", "浑厚", "低沉", "沧桑", "大叔", "老者", "御姐"),
    ),
    (
        ("沙哑", "有磁性"),
        ("清脆童声", "童声", "稚嫩", "甜美", "萝莉", "小孩", "儿童"),
    ),
    (
        ("苍老",),
        ("清脆童声", "童声", "稚嫩", "甜美", "萝莉", "小孩", "儿童", "少女"),
    ),
)


def gender_label(gender: Any) -> str:
    return _GENDER_LABELS.get(str(gender or "").strip().lower(), "中性")


def infer_age_group(age: Any) -> str:
    try:
        value = int(age)
    except (TypeError, ValueError):
        return "青年"
    if value < 13:
        return "儿童"
    if value < 19:
        return "青少年"
    if value < 36:
        return "青年"
    if value < 56:
        return "中年"
    return "老年"


def infer_pitch(tone: Any, gender: Any) -> str:
    text = str(tone or "")
    if "低" in text or "沉" in text:
        return "偏低"
    if "清亮" in text or "明快" in text or "甜" in text:
        return "偏高"
    if str(gender or "").strip().lower() == "male":
        return "中低音"
    return "中音"


def sanitize_voice_description(value: Any) -> str:
    result = str(value or "").strip()
    for term in (*_VAGUE_TERMS, *_IMITATION_TERMS):
        result = result.replace(term, "")
    return " ".join(result.split())


def stable_voice_description(value: Any) -> str:
    """Remove segment-level pace and emotion from a fixed voice description."""

    sanitized = sanitize_voice_description(value)
    fields = _parse_voice_description_fields(sanitized)
    if fields:
        stable_fields = ("性别", "年龄感", "音调", "特点", "用途")
        return "，".join(
            f"{field_name}：{fields[field_name]}"
            for field_name in stable_fields
            if fields.get(field_name)
        )

    clauses = [
        clause.strip()
        for clause in re.split(r"[，,；;]+", sanitized)
        if clause.strip()
    ]
    return "，".join(
        clause
        for clause in clauses
        if not re.match(r"^(?:语速|情绪)(?:[:：]|为|偏|较|很|极|缓|快|慢)", clause)
    )


def _parse_voice_description_fields(value: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    text = str(value or "").strip()
    if not text:
        return fields

    for index, field_name in enumerate(_DESCRIPTION_FIELD_NAMES):
        marker = f"{field_name}："
        start = text.find(marker)
        if start < 0:
            continue
        value_start = start + len(marker)
        next_positions = [
            text.find(f"{next_name}：", value_start)
            for next_name in _DESCRIPTION_FIELD_NAMES[index + 1 :]
        ]
        next_positions = [position for position in next_positions if position >= 0]
        value_end = min(next_positions) if next_positions else len(text)
        field_value = text[value_start:value_end].strip(" ，,；;")
        if field_value:
            fields[field_name] = field_value
    return fields


def build_quality_voice_description(
    *,
    gender: Any,
    age_group: Any,
    pitch: Any,
    pace: Any,
    emotion: Any,
    traits: Iterable[Any],
    use_case: Any,
) -> str:
    """Build a compact, multi-dimensional voice description.

    画像未标注（空值）的维度直接省略整条子句：这段文本会进入 TTS 提示词，
    写成"未标注"或伪造默认值都会被模型当成音色事实。
    """

    trait_text = "、".join(str(item).strip() for item in traits if str(item or "").strip())
    clauses: List[str] = [f"性别：{gender_label(gender)}"]
    for label, value in (
        ("年龄感", age_group),
        ("音调", pitch),
        ("语速", pace),
        ("情绪", emotion),
        ("特点", trait_text or "吐字清晰"),
        ("用途", use_case),
    ):
        text = str(value or "").strip()
        if text:
            clauses.append(f"{label}：{text}")
    return "，".join(clauses)


def _voice_traits(entry: Dict[str, Any]) -> List[str]:
    profile = entry.get("voice_profile") or {}
    if isinstance(profile, dict):
        profile_traits = profile.get("timbre_traits")
        if isinstance(profile_traits, list):
            traits = [str(item).strip() for item in profile_traits if str(item or "").strip()]
            if traits:
                return traits

    style = str(entry.get("style") or "").strip()
    description = str(entry.get("description") or "").strip()
    traits = list(_STYLE_TRAITS.get(style, []))
    for token in ("亲切自然", "温柔", "清晰", "沙哑", "磁性", "甜美", "有力", "活力"):
        if token in description and token not in traits:
            traits.append(token)
    return traits or ["吐字清晰"]


def _voice_profile_from_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    style = str(entry.get("style") or "").strip()
    catalog_profile = entry.get("voice_profile") or {}
    if not isinstance(catalog_profile, dict):
        catalog_profile = {}
    return {
        "gender": str(entry.get("gender") or "neutral").strip().lower(),
        # 年龄感与语速只认目录条目自带的 voice_profile 实测值，缺失即空（pending）：
        # 历史上曾有一张按声线名硬编码的年龄提示表，键全部属于已退役的音色空间，
        # 对现役目录（含 MiMo 的同名英文预置音）都产出与兜底值相同的结果，故已删除；
        # 音调仍保留按官方 style 标签的映射，因为那是目录自带事实的推导而非听测结论。
        "age_group": str(catalog_profile.get("age_group") or "").strip(),
        "pitch": str(catalog_profile.get("pitch") or _PITCH_BY_STYLE.get(style, "中音")).strip(),
        "pace": str(catalog_profile.get("pace") or "").strip(),
        "traits": _voice_traits(entry),
    }


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _has_timbre_conflict(target_traits: Iterable[Any], requested_text: str) -> bool:
    trait_text = "、".join(str(item or "").strip() for item in target_traits)
    if not trait_text or not requested_text:
        return False
    return any(
        _contains_any(trait_text, target_terms) and _contains_any(requested_text, opposing_terms)
        for target_terms, opposing_terms in _TIMBRE_CONFLICT_RULES
    )


def reconcile_voice_description_with_selected_voice(
    *,
    model: Any,
    voice_id: Any,
    requested_description: Any = "",
    fallback_emotion: Any = "平静",
    fallback_use_case: Any = "有声书角色对白",
) -> VoiceDescriptionResult:
    """Keep selected voice metadata as hard constraints for style prompts."""

    voice = str(voice_id or "").strip()
    sanitized = sanitize_voice_description(requested_description)
    if not voice:
        return VoiceDescriptionResult(description=sanitized)

    entry: Optional[Dict[str, Any]] = get_voice_entry(voice, str(model or DEFAULT_AUDIOBOOK_TTS_MODEL))
    if not entry:
        return VoiceDescriptionResult(description=sanitized)

    profile = _voice_profile_from_entry(entry)
    requested_fields = _parse_voice_description_fields(sanitized)
    warnings: List[str] = []
    target_gender = gender_label(profile["gender"])
    opposite_gender = "男性" if target_gender == "女性" else "女性" if target_gender == "男性" else ""
    if opposite_gender and opposite_gender in sanitized:
        warnings.append(f"声音描述性别与已选音色 {voice} 冲突，已按音色修正为{target_gender}。")
    elif target_gender in {"男性", "女性"} and requested_fields.get("性别") == "中性":
        warnings.append(f"声音描述性别与已选音色 {voice} 不一致，已按音色修正为{target_gender}。")

    # 画像未标注年龄时不判冲突，也不改写用户原文：没有听测证据就没有修正依据。
    target_age = profile["age_group"]
    if target_age:
        for age_token in _AGE_PROFILE_TOKENS:
            if age_token != target_age and age_token in sanitized:
                warnings.append(f"声音描述年龄感与已选音色 {voice} 冲突，已按音色修正为{target_age}。")
                break

    target_pitch = profile["pitch"]
    requested_pitch = requested_fields.get("音调", "")
    if requested_pitch and requested_pitch != target_pitch:
        low_requested_high_voice = "低" in requested_pitch and "高" in target_pitch
        high_requested_low_voice = "高" in requested_pitch and "低" in target_pitch
        if low_requested_high_voice or high_requested_low_voice:
            warnings.append(f"声音描述音调与已选音色 {voice} 冲突，已按音色修正为{target_pitch}。")

    requested_timbre = requested_fields.get("特点", "") or sanitized
    if _has_timbre_conflict(profile["traits"], requested_timbre):
        traits_text = "、".join(profile["traits"])
        warnings.append(f"声音描述音质与已选音色 {voice} 冲突，已按音色特点修正为{traits_text}。")

    requested_use_case = requested_fields.get("用途", "")
    segment_type = str(fallback_use_case or "").strip()
    is_narration_use_case = "旁白" in requested_use_case or "旁白" in segment_type
    if not is_narration_use_case and any(term in requested_use_case for term in _NARRATION_USE_CASE_TERMS):
        warnings.append(f"声音描述用途与角色对白场景冲突，已修正为有声书角色对白。")
        requested_use_case = "有声书角色对白"

    description = build_quality_voice_description(
        gender=profile["gender"],
        age_group=target_age or requested_fields.get("年龄感", ""),
        pitch=profile["pitch"],
        pace=requested_fields.get("语速") or profile["pace"],
        emotion=requested_fields.get("情绪") or fallback_emotion,
        traits=profile["traits"],
        use_case=requested_use_case or fallback_use_case,
    )
    return VoiceDescriptionResult(description=description, warnings=warnings)
