"""Segment-level audiobook delivery planning for TTS style control."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from app.services.audiobook.tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    get_audiobook_tts_style_capabilities,
    model_uses_basic_numeric_speed_control,
    normalize_audiobook_tts_model,
)


def resolve_segment_tts_model(voice_params: Dict[str, Any], default_model: Any = None) -> str:
    """Resolve the concrete TTS model for a single segment."""

    return normalize_audiobook_tts_model(
        (voice_params or {}).get("tts_model") or default_model or DEFAULT_AUDIOBOOK_TTS_MODEL
    )


def model_family(model: Any) -> str:
    normalized = normalize_audiobook_tts_model(model, default=str(model or ""))
    return str(get_audiobook_tts_style_capabilities(normalized).get("model_family") or "generic")


def preferred_control_mode(model: Any, voice_params: Dict[str, Any] | None = None) -> str:
    params = dict(voice_params or {})
    explicit = str(
        params.get("style_control_method")
        or params.get("style_control_mode")
        or params.get("control_method")
        or ""
    ).strip().lower()
    aliases = {
        "tags": "audio_tags",
        "label": "audio_tags",
        "labels": "audio_tags",
        "instruct": "natural_language",
        "instruction": "natural_language",
    }
    explicit = aliases.get(explicit, explicit)
    capabilities = get_audiobook_tts_style_capabilities(model)
    modes = _coerce_string_list(capabilities.get("style_control_modes"))
    if explicit and explicit in modes:
        return explicit
    return _text(capabilities.get("preferred_style_control_mode")) or "natural_language"


def build_delivery_plan(
    *,
    segment: Any = None,
    voice_params: Dict[str, Any] | None = None,
    model: Any = None,
    emotion: Any = "neutral",
) -> Dict[str, Any]:
    """Build or complete a segment-level delivery plan.

    The plan is intentionally model-aware but provider-neutral: it records the
    resolved model family and desired performance so provider adapters can
    compile it into natural-language instructions, director prompts, or tags.
    """

    params = dict(voice_params or {})
    resolved_model = resolve_segment_tts_model(params, model)
    existing = params.get("delivery_plan") if isinstance(params.get("delivery_plan"), dict) else {}
    plan: Dict[str, Any] = dict(existing or {})

    segment_type = _first_text(
        plan.get("segment_type"),
        getattr(segment, "type", ""),
        params.get("segment_type"),
    )
    speaker = _first_text(
        plan.get("speaker"),
        getattr(segment, "speaker", ""),
        params.get("segment_speaker"),
    )
    performance_notes = _first_text(
        getattr(segment, "performance_notes", ""),
        params.get("performance_notes"),
        plan.get("performance_notes"),
    )
    text = _first_text(getattr(segment, "text", ""), params.get("text"))
    target_emotion = _first_text(
        plan.get("emotion_primary"),
        params.get("instruct_emotion"),
        getattr(segment, "instruct_emotion", ""),
        emotion,
        params.get("emotion"),
        getattr(segment, "emotion", ""),
        "neutral",
    )

    plan["model"] = resolved_model
    plan["tts_model"] = resolved_model
    voice_id = _first_text(plan.get("voice_id"), params.get("speaker"), params.get("voice_id"))
    plan.setdefault("voice_id", voice_id)
    if text:
        plan.setdefault("text", text)
    style_capabilities = get_audiobook_tts_style_capabilities(resolved_model)
    plan["model_family"] = _text(style_capabilities.get("model_family")) or model_family(resolved_model)
    plan["model_control_preference"] = preferred_control_mode(resolved_model, params)
    plan["model_style_control_modes"] = _coerce_string_list(style_capabilities.get("style_control_modes"))
    plan["supports_audio_tags"] = bool(style_capabilities.get("supports_audio_tags"))
    plan.setdefault("segment_type", segment_type or "narration")
    if speaker:
        plan.setdefault("speaker", speaker)
    plan.setdefault("delivery_mode", _infer_delivery_mode(segment_type, target_emotion, performance_notes, text))
    plan.setdefault("emotion_primary", target_emotion or "neutral")
    plan.setdefault("emotion", target_emotion or "neutral")
    plan.setdefault("emotion_mix", _infer_emotion_mix(performance_notes))
    plan.setdefault(
        "pace",
        _infer_pace(
            params,
            performance_notes,
            allow_numeric_fallback=model_uses_basic_numeric_speed_control(resolved_model),
        ),
    )
    # Segment-level pitch is a voice-identity control, not a performance
    # control. Keep it out of the provider-neutral plan for every model.
    plan.pop("pitch", None)
    plan.setdefault("intensity", _infer_intensity(plan["delivery_mode"], target_emotion, performance_notes))
    plan.setdefault("micro_tags", _infer_micro_tags(performance_notes, text))
    pause_strategy = _infer_pause_strategy(performance_notes)
    if pause_strategy:
        plan.setdefault("pause_strategy", pause_strategy)
    plan.setdefault("pause_profile", _infer_pause_profile(performance_notes, text))
    timeline_pause_after_ms = _coerce_timeline_pause_ms(
        plan.get("timeline_pause_after_ms", params.get("timeline_pause_after_ms")),
    )
    if timeline_pause_after_ms is not None:
        plan["timeline_pause_after_ms"] = timeline_pause_after_ms
    cadence_profile = _first_text(plan.get("cadence_profile"), params.get("cadence_profile"))
    cadence_reason = _first_text(plan.get("cadence_reason"), params.get("cadence_reason"))
    if cadence_profile:
        plan["cadence_profile"] = cadence_profile
    if cadence_reason:
        plan["cadence_reason"] = cadence_reason
    stress_words = _coerce_string_list(plan.get("stress_words")) or _infer_stress_words(performance_notes)
    if stress_words:
        plan["stress_words"] = stress_words
    ending_style = _first_text(plan.get("ending_style"), _infer_ending_style(performance_notes))
    if ending_style:
        plan["ending_style"] = ending_style
    role = _first_text(
        params.get("instruct_role"),
        getattr(segment, "instruct_role", ""),
        plan.get("director_role"),
    )
    scene = _first_text(plan.get("director_scene"), params.get("instruct_scene"), getattr(segment, "instruct_scene", ""))
    identity = _first_text(
        plan.get("director_identity"),
        params.get("instruct_identity"),
        getattr(segment, "instruct_identity", ""),
    )
    if role:
        plan["director_role"] = role
    if scene:
        plan.setdefault("director_scene", scene)
    if identity:
        plan.setdefault("director_identity", identity)
    auto_guidance_values = {
        value
        for value in (
            performance_notes,
            _text(plan.get("performance_notes")),
            _text(plan.get("style_instruction")),
        )
        if value
    }
    guidance = next(
        (
            candidate
            for candidate in (
                _text(plan.get("director_guidance")),
                _text(params.get("instructions")),
            )
            if candidate and candidate not in auto_guidance_values
        ),
        "",
    )
    if guidance:
        plan["director_guidance"] = guidance
    else:
        plan.pop("director_guidance", None)
    style_instruction = _build_style_instruction(plan, performance_notes)
    if style_instruction:
        plan["style_instruction"] = style_instruction
    else:
        plan.pop("style_instruction", None)

    return _compact_plan(plan)


def delivery_plan_instruction_parts(plan: Dict[str, Any] | None) -> List[str]:
    value = dict(plan or {})
    parts: List[str] = []
    delivery_mode = _text(value.get("delivery_mode"))
    pace = _text(value.get("pace"))
    intensity = _text(value.get("intensity"))
    emotion_mix = _coerce_string_list(value.get("emotion_mix"))
    micro_tags = _coerce_string_list(value.get("micro_tags"))
    pause_strategy = _text(value.get("pause_strategy"))
    stress_words = _coerce_string_list(value.get("stress_words"))
    ending_style = _text(value.get("ending_style"))
    guidance = _text(value.get("director_guidance"))

    if delivery_mode:
        parts.append(f"朗读方式：{delivery_mode}")
    if pace or intensity:
        controls = []
        if pace:
            controls.append(f"语速={pace}")
        if intensity:
            controls.append(f"强度={intensity}")
        parts.append("韵律控制：" + "，".join(controls))
    if emotion_mix:
        parts.append("情绪层次：" + "、".join(emotion_mix))
    if micro_tags:
        parts.append("微表演标签：" + "、".join(micro_tags))
    if pause_strategy:
        parts.append(f"停顿策略：{pause_strategy}")
    cadence_profile = _text(value.get("cadence_profile"))
    cadence_reason = _text(value.get("cadence_reason"))
    timeline_pause_after_ms = _coerce_timeline_pause_ms(value.get("timeline_pause_after_ms"))
    if cadence_profile or cadence_reason or timeline_pause_after_ms is not None:
        cadence_parts = [part for part in (cadence_profile, cadence_reason) if part]
        if timeline_pause_after_ms is not None:
            cadence_parts.append(f"后期留白{timeline_pause_after_ms}毫秒")
        parts.append("剧情节奏：" + "，".join(cadence_parts))
    if stress_words:
        parts.append("重读词：" + "、".join(stress_words))
    if ending_style == "lengthened":
        parts.append("收尾方式：句尾拖长")
    elif ending_style == "clipped":
        parts.append("收尾方式：短促收尾")
    if guidance:
        parts.append(f"导演指导：{guidance}")
    return parts


def delivery_plan_style_tags(plan: Dict[str, Any] | None, fallback_emotion: Any = "") -> List[str]:
    value = dict(plan or {})
    tags = _coerce_string_list(value.get("style_tags"))
    emotion = _text(value.get("emotion_primary")) or _text(fallback_emotion)
    if emotion and emotion != "neutral":
        tags.append(emotion)
    tags.extend(_coerce_string_list(value.get("emotion_mix")))
    return _unique(tags)


def delivery_plan_inline_tags(plan: Dict[str, Any] | None) -> List[str]:
    value = dict(plan or {})
    tags = _coerce_string_list(value.get("inline_audio_tags"))
    tags.extend(_coerce_string_list(value.get("micro_tags")))
    return _unique(tags)


def _infer_delivery_mode(segment_type: str, emotion: str, notes: str, text: str) -> str:
    source = f"{notes} {text}".lower()
    if _contains_any(source, ("哽咽", "抽泣", "哭腔", "呜咽", "sob", "cry")):
        return "sob"
    if _contains_any(source, ("低语", "耳语", "压低声音", "小声", "whisper")):
        return "whisper"
    if _contains_any(source, ("大喊", "怒吼", "喊", "嘶吼", "shout", "yell")):
        return "shout"
    if _contains_any(source, ("轻笑", "大笑", "冷笑", "笑", "laugh")):
        return "laugh"
    normalized_type = _text(segment_type).lower()
    if normalized_type in {"dialogue", "monologue", "narration"}:
        return normalized_type
    normalized_emotion = _text(emotion).lower()
    return "dialogue" if normalized_emotion in {"angry", "sad", "happy", "fearful"} else "narration"


def _infer_emotion_mix(notes: str) -> List[str]:
    source = _text(notes)
    candidates = ("压抑", "悲伤", "愤怒", "温柔", "疲惫", "委屈", "恐惧", "紧张", "兴奋", "冷漠")
    return [item for item in candidates if item in source]


def _infer_pace(
    params: Dict[str, Any],
    notes: str,
    *,
    allow_numeric_fallback: bool = True,
) -> str:
    source = _text(notes)
    if _contains_any(source, ("极慢", "偏慢", "放慢", "缓慢", "慢速")):
        return "slow"
    if _contains_any(source, ("偏快", "加快", "快速", "急促")):
        return "fast"
    if not allow_numeric_fallback:
        return "medium"
    raw_speed = params.get("rate", params.get("speed"))
    try:
        speed = float(raw_speed)
    except (TypeError, ValueError):
        return "medium"
    if speed < 0.92:
        return "slow"
    if speed > 1.08:
        return "fast"
    return "medium"


def _infer_intensity(delivery_mode: str, emotion: str, notes: str) -> str:
    source = _text(notes)
    if delivery_mode == "shout" or _text(emotion).lower() in {"angry", "excited"}:
        return "high"
    if delivery_mode == "whisper" or _contains_any(source, ("轻微", "克制", "有气无力")):
        return "low"
    return "medium"


def _infer_micro_tags(notes: str, text: str) -> List[str]:
    source = f"{notes} {text}"
    mapping = (
        ("哽咽", ("哽咽", "抽泣", "哭腔", "呜咽")),
        ("低语", ("低语", "耳语", "压低声音", "小声")),
        ("轻笑", ("轻笑", "苦笑")),
        ("大笑", ("大笑", "放声笑")),
        ("叹气", ("叹气", "叹息")),
        ("吸气", ("吸气", "深呼吸", "倒吸")),
        ("喘息", ("喘息", "急促呼吸")),
        ("咳嗽", ("咳嗽",)),
        ("破音", ("破音",)),
        ("气声", ("气音", "气声")),
    )
    return [tag for tag, keywords in mapping if _contains_any(source, keywords)]


def _infer_pause_strategy(notes: str) -> str:
    source = _text(notes)
    pause_clauses = [
        clause.strip()
        for clause in re.split(r"[，,；;。！？!?]+", source)
        if clause.strip()
        and _contains_any(
            clause,
            ("留白", "停顿", "短停", "长停", "停半拍", "停一下", "pause"),
        )
    ]
    return "，".join(_unique(pause_clauses))


def _infer_stress_words(notes: str) -> List[str]:
    patterns = (
        r"(?:重读|强调|加重)\s*[\"'“‘]?([^\"'”’\s，。！？；：]{1,12})[\"'”’]?\s*字?",
        r"[\"'“‘]([^\"'”’]{1,12})[\"'”’]\s*字?\s*(?:重读|强调|加重)",
    )
    values: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, _text(notes)):
            value = match.group(1).strip()
            if value and value not in values:
                values.append(value)
    return values[:8]


def _infer_ending_style(notes: str) -> str:
    source = _text(notes)
    if _contains_any(source, ("句尾拖长", "尾音拖长", "尾音拉长", "结尾拖长")):
        return "lengthened"
    if _contains_any(source, ("句尾收紧", "短促收尾", "干脆收尾")):
        return "clipped"
    return ""


def _infer_pause_profile(notes: str, text: str) -> str:
    source = f"{notes} {text}"
    if _contains_any(source, ("留白", "长停顿", "停顿", "……", "...")):
        return "dramatic"
    if _contains_any(source, ("，", ",", "、", ";", "；")):
        return "natural"
    return "balanced"


def _build_style_instruction(plan: Dict[str, Any], notes: str) -> str:
    explicit = _text(notes)
    if explicit:
        return explicit

    parts: List[str] = []
    emotion = _text(plan.get("emotion") or plan.get("emotion_primary"))
    pace = _text(plan.get("pace"))
    intensity = _text(plan.get("intensity"))
    pause_profile = _text(plan.get("pause_profile"))
    if emotion and emotion != "neutral":
        parts.append(f"情绪保持{emotion}")
    if pace and pace != "medium":
        parts.append(f"语速{pace}")
    if intensity and intensity != "medium":
        parts.append(f"强度{intensity}")
    if pause_profile and pause_profile != "balanced":
        parts.append(f"停顿{pause_profile}")
    return "，".join(parts)


def _compact_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for key, value in plan.items():
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                output[key] = cleaned
        elif isinstance(value, list):
            cleaned_list = _unique(_coerce_string_list(value))
            if cleaned_list:
                output[key] = cleaned_list
        elif value not in (None, "", {}, []):
            output[key] = value
    return output


def _coerce_timeline_pause_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        pause_ms = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if pause_ms <= 0:
        return None
    return max(80, min(3000, pause_ms))


def _contains_any(value: str, needles: Iterable[str]) -> bool:
    return any(needle and needle.lower() in value.lower() for needle in needles)


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [_text(item) for item in value if _text(item)]
    return []


def _unique(values: Iterable[Any]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for item in values:
        value = _text(item)
        if not value or value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output
