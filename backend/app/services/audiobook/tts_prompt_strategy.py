"""Pure prompt strategy helpers for audiobook TTS style control."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from app.services.audiobook.tts_delivery_plan import (
    delivery_plan_inline_tags,
    delivery_plan_instruction_parts,
)
from app.services.audiobook.tts_model_ids import (
    get_audiobook_tts_style_capabilities,
    normalize_audiobook_tts_emotion,
)
from app.services.audiobook.voice_description_policy import sanitize_voice_description


@dataclass(frozen=True)
class _CommonPromptContext:
    voice_description: str = ""
    segment_speaker: str = ""
    segment_type: str = ""
    role: str = ""
    identity: str = ""
    scene: str = ""
    target_emotion: str = ""
    performance_notes: str = ""
    delivery_plan: Dict[str, Any] = field(default_factory=dict)
    delivery_plan_parts: List[str] = field(default_factory=list)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique_nonempty(values: List[Any]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for item in values:
        value = _text(item)
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _measure_text(value: str) -> int:
    return len(str(value or ""))


def _truncate_text_boundary(value: str, budget: int) -> str:
    text = _text(value)
    if budget <= 0 or not text:
        return ""
    if _measure_text(text) <= budget:
        return text
    if budget <= 1:
        return "…"

    truncated = text[: max(0, budget - 1)].rstrip("；;，,、 ")
    boundary = max(
        truncated.rfind(mark)
        for mark in ("。", "！", "？", "；", ";", "，", ",")
    )
    if boundary >= max(6, int(len(truncated) * 0.5)):
        truncated = truncated[: boundary + 1].rstrip("；;，,、 ")
    return f"{truncated}…".strip()


def measure_cosyvoice_instruction_units(value: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in str(value or ""))


def truncate_cosyvoice_instruction_units(value: str, budget: int) -> str:
    text = _text(value)
    if budget <= 0 or not text:
        return ""

    output: List[str] = []
    used = 0
    for char in text:
        cost = 2 if ord(char) > 127 else 1
        if used + cost > budget:
            break
        output.append(char)
        used += cost
    return "".join(output).rstrip("；;，,、 ")


def compact_instruction_parts(
    parts: List[str],
    budget: int | None,
    *,
    measure_text: Callable[[str], int] | None = None,
    truncate_text: Callable[[str, int], str] | None = None,
) -> tuple[str, Dict[str, Any], List[str]]:
    clean_parts = _unique_nonempty(parts)
    if not clean_parts:
        return "", {}, []

    measure = measure_text or _measure_text
    truncate = truncate_text or _truncate_text_boundary

    if not budget or budget <= 0:
        instruction = "；".join(clean_parts).strip("；")
        return (
            instruction,
            {
                "limit": None,
                "used": measure(instruction),
                "truncated": False,
                "dropped_fields": [],
            },
            [],
        )

    output_parts: List[str] = []
    dropped_fields: List[str] = []
    truncated = False

    for index, part in enumerate(clean_parts):
        delimiter_cost = measure("；") if output_parts else 0
        used = measure("；".join(output_parts))
        remaining = budget - used - delimiter_cost
        if remaining <= 0:
            dropped_fields.extend(clean_parts[index:])
            break
        if measure(part) <= remaining:
            output_parts.append(part)
            continue
        compacted = truncate(part, remaining)
        if compacted:
            output_parts.append(compacted)
        dropped_fields.extend(clean_parts[index + 1 :])
        truncated = True
        break

    instruction = "；".join(output_parts).strip("；")
    used = measure(instruction)
    budget_payload = {
        "limit": budget,
        "used": used,
        "truncated": truncated or bool(dropped_fields),
        "dropped_fields": dropped_fields,
    }
    warnings = [f"instruction 已按 {budget} 字预算压缩"] if budget_payload["truncated"] else []
    return instruction, budget_payload, warnings


def _coerce_string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [_text(item) for item in value if _text(item)]
    return []


def _coerce_pause_seconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        pause_seconds = float(value)
    except (TypeError, ValueError):
        return None
    if pause_seconds <= 0:
        return None
    return round(max(0.1, min(2.0, pause_seconds)), 2)


def _format_pause_seconds(value: float) -> str:
    rounded = round(value, 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _delivery_plan_pause_seconds(plan: Dict[str, Any]) -> float | None:
    explicit = _coerce_pause_seconds(plan.get("pause_after"))
    if explicit is not None:
        return explicit
    if _text(plan.get("pause_profile")).lower() == "dramatic":
        return 0.8
    return None


def render_stepaudio_inline_prefix(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    delivery_plan = voice_params.get("delivery_plan") if isinstance(voice_params.get("delivery_plan"), dict) else {}
    pause_seconds = (
        _coerce_pause_seconds(voice_params.get("pause_before"))
        or _delivery_plan_pause_seconds(delivery_plan)
    )
    inline_tags = _unique_nonempty(_coerce_string_list(voice_params.get("inline_audio_tags")))
    inline_tags.extend(tag for tag in delivery_plan_inline_tags(delivery_plan) if tag not in inline_tags)
    inline_tags.extend(tag for tag in _coerce_string_list(delivery_plan.get("emotion_mix")) if tag not in inline_tags)

    chunks: List[str] = []
    if pause_seconds is not None:
        chunks.append(f"（停顿{_format_pause_seconds(pause_seconds)}秒）")
    chunks.extend(f"（{tag}）" for tag in inline_tags)
    return "".join(chunks)


def _delivery_plan_parts_matching(parts: List[str], prefixes: tuple[str, ...]) -> List[str]:
    return [part for part in parts if part.startswith(prefixes)]


def _delivery_plan_parts_except(parts: List[str], prefixes: tuple[str, ...]) -> List[str]:
    return [part for part in parts if not part.startswith(prefixes)]


def _build_common_prompt_context(
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
    *,
    model: Any = None,
) -> _CommonPromptContext:
    target_emotion = _text(voice_params.get("instruct_emotion")) or _text(emotion)
    if model is not None:
        target_emotion = normalize_audiobook_tts_emotion(target_emotion, model)
    return _CommonPromptContext(
        voice_description=sanitize_voice_description(voice_params.get("voice_description")),
        segment_speaker=_text(voice_params.get("segment_speaker")),
        segment_type=_text(voice_params.get("segment_type")),
        role=_text(voice_params.get("instruct_role")),
        identity=_text(voice_params.get("instruct_identity")),
        scene=_text(voice_params.get("instruct_scene")),
        target_emotion=target_emotion,
        performance_notes=_text(voice_params.get("performance_notes")),
        delivery_plan_parts=delivery_plan_instruction_parts(voice_params.get("delivery_plan")),
        delivery_plan=dict(voice_params.get("delivery_plan") or {})
        if isinstance(voice_params.get("delivery_plan"), dict)
        else {},
    )


def _build_narration_parts(context: _CommonPromptContext) -> List[str]:
    parts: List[str] = ["旁白模板：讲述者视角，信息清晰，语气稳定"]
    rhythm_parts = _delivery_plan_parts_matching(context.delivery_plan_parts, ("韵律控制：", "停顿策略："))
    remaining_plan_parts = _delivery_plan_parts_except(context.delivery_plan_parts, ("韵律控制：", "停顿策略："))

    if context.voice_description:
        parts.append(f"声音描述：{context.voice_description}")
    if context.segment_type:
        parts.append(f"片段类型：{context.segment_type}")
    parts.extend(rhythm_parts)
    if context.target_emotion and context.target_emotion != "neutral":
        parts.append(f"情绪目标：{context.target_emotion}")
    if context.performance_notes:
        parts.append(f"演绎要求：{context.performance_notes}")
    if context.scene:
        parts.append(f"场景氛围：{context.scene}")
    if context.role:
        parts.append(f"角色设定：{context.role}")
    if context.identity:
        parts.append(f"身份设定：{context.identity}")
    parts.extend(remaining_plan_parts)
    return parts


def _build_dialogue_parts(context: _CommonPromptContext) -> List[str]:
    parts: List[str] = []
    if context.voice_description:
        parts.append(f"声音描述：{context.voice_description}")
    if context.segment_speaker and context.segment_speaker != "旁白":
        parts.append(f"说话角色：{context.segment_speaker}")
    parts.append("对白模板：突出角色身份、情绪强度与场景张力")
    if context.segment_type:
        parts.append(f"片段类型：{context.segment_type}")
    if context.role:
        parts.append(f"角色设定：{context.role}")
    if context.identity:
        parts.append(f"身份设定：{context.identity}")
    if context.target_emotion and context.target_emotion != "neutral":
        parts.append(f"情绪目标：{context.target_emotion}")
    if context.scene:
        parts.append(f"场景氛围：{context.scene}")
    if context.performance_notes:
        parts.append(f"演绎要求：{context.performance_notes}")
    parts.extend(context.delivery_plan_parts)
    return parts


def _build_monologue_parts(context: _CommonPromptContext) -> List[str]:
    parts: List[str] = ["内心独白模板：贴近心理活动，低强度、近耳感"]
    if context.voice_description:
        parts.append(f"声音描述：{context.voice_description}")
    if context.segment_type:
        parts.append(f"片段类型：{context.segment_type}")
    if context.target_emotion and context.target_emotion != "neutral":
        parts.append(f"情绪目标：{context.target_emotion}")
    if context.performance_notes:
        parts.append(f"演绎要求：{context.performance_notes}")
    if context.segment_speaker and context.segment_speaker != "旁白":
        parts.append(f"说话角色：{context.segment_speaker}")
    if context.role:
        parts.append(f"角色设定：{context.role}")
    if context.identity:
        parts.append(f"身份设定：{context.identity}")
    if context.scene:
        parts.append(f"场景氛围：{context.scene}")
    parts.extend(context.delivery_plan_parts)
    return parts


def _build_generic_parts(context: _CommonPromptContext) -> List[str]:
    parts: List[str] = []
    if context.voice_description:
        parts.append(f"声音描述：{context.voice_description}")
    if context.segment_speaker and context.segment_speaker != "旁白":
        parts.append(f"说话角色：{context.segment_speaker}")
    if context.segment_type:
        parts.append(f"片段类型：{context.segment_type}")
    if context.role:
        parts.append(f"角色设定：{context.role}")
    if context.identity:
        parts.append(f"身份设定：{context.identity}")
    if context.scene:
        parts.append(f"场景氛围：{context.scene}")
    if context.target_emotion and context.target_emotion != "neutral":
        parts.append(f"情绪目标：{context.target_emotion}")
    if context.performance_notes:
        parts.append(f"演绎要求：{context.performance_notes}")
    parts.extend(context.delivery_plan_parts)
    return parts


def _compact_cosyvoice_value(value: Any, max_units: int) -> str:
    return truncate_cosyvoice_instruction_units(_text(value), max_units)


def _split_cosyvoice_note_clauses(value: str) -> List[str]:
    clauses: List[str] = []
    current: List[str] = []
    for char in _text(value):
        if char in "，,；;。！？!?":
            clause = "".join(current).strip()
            if clause:
                clauses.append(clause)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        clauses.append(tail)
    return clauses


def _cosyvoice_short_action_cue(notes: str) -> str:
    clauses = _split_cosyvoice_note_clauses(notes)
    if not clauses:
        return ""

    priority_keywords = (
        "情绪",
        "压住",
        "克制",
        "稳住",
        "收住",
        "压低",
        "低声",
        "低语",
        "哽咽",
        "哭腔",
        "轻笑",
        "大喊",
        "喊",
        "结尾",
        "尾音",
        "不要",
        "别",
        "加重",
    )
    selected = [clause for clause in clauses if any(keyword in clause for keyword in priority_keywords)]
    if not selected:
        selected = clauses[:1]
    elif len(selected) > 1:
        selected = [selected[0], selected[-1]]
    return _compact_cosyvoice_value(",".join(selected[:2]), 28)


def _cosyvoice_pause_cue(plan: Dict[str, Any], stress_words: List[str]) -> str:
    pause_strategy = _text(plan.get("pause_strategy"))
    if pause_strategy and _text(plan.get("pause_profile")).lower() == "dramatic":
        target = stress_words[0] if stress_words else ""
        if target:
            return _compact_cosyvoice_value(f"{target}前短停", 30)
        return "句尾留白"
    if pause_strategy:
        return _compact_cosyvoice_value(pause_strategy, 30)
    if _text(plan.get("pause_profile")).lower() == "dramatic":
        return "句尾留白"
    return ""


def _build_cosyvoice_parts(context: _CommonPromptContext) -> List[str]:
    plan = dict(context.delivery_plan or {})
    parts: List[str] = []

    if context.target_emotion and context.target_emotion != "neutral":
        parts.append(f"emotion={context.target_emotion}")

    stress_words = _coerce_string_list(plan.get("stress_words"))
    pause_cue = _cosyvoice_pause_cue(plan, stress_words)
    if pause_cue:
        parts.append(f"pause={pause_cue}")

    if stress_words:
        parts.append("重读=" + _compact_cosyvoice_value("、".join(stress_words), 26))

    action_cue = _cosyvoice_short_action_cue(
        context.performance_notes
        or _text(plan.get("director_guidance"))
        or _text(plan.get("style_instruction"))
    )
    if action_cue:
        parts.append(f"act={action_cue}")

    delivery_mode = _text(plan.get("delivery_mode"))
    if delivery_mode and delivery_mode not in {"narration", "dialogue", "monologue"}:
        parts.append(f"mode={delivery_mode}")

    micro_tags = _coerce_string_list(plan.get("micro_tags"))
    if micro_tags:
        parts.append("tag=" + _compact_cosyvoice_value("、".join(micro_tags), 20))

    if not parts and context.segment_type:
        parts.append(f"type={context.segment_type}")

    return parts


def _build_stepaudio_parts(context: _CommonPromptContext) -> List[str]:
    parts: List[str] = []

    if context.segment_speaker and context.segment_speaker != "旁白":
        parts.append(f"说话角色：{context.segment_speaker}")
    if context.target_emotion and context.target_emotion != "neutral":
        parts.append(f"情绪目标：{context.target_emotion}")

    priority_plan_parts = _delivery_plan_parts_matching(
        context.delivery_plan_parts,
        ("停顿策略：", "重读词：", "韵律控制：", "导演指导：", "朗读方式："),
    )
    parts.extend(priority_plan_parts)

    if context.performance_notes:
        parts.append(f"演绎要求：{context.performance_notes}")
    if context.role:
        parts.append(f"角色设定：{context.role}")
    if context.identity:
        parts.append(f"身份设定：{context.identity}")
    if context.scene:
        parts.append(f"场景氛围：{context.scene}")
    if context.segment_type:
        parts.append(f"片段类型：{context.segment_type}")
    if context.voice_description:
        parts.append(f"声音描述：{context.voice_description}")

    return parts


def _prompt_model_family(model: Any) -> str:
    return _text(get_audiobook_tts_style_capabilities(model).get("model_family"))


def build_common_prompt_parts(
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
    *,
    model: Any = None,
) -> List[str]:
    context = _build_common_prompt_context(voice_params, emotion, model=model)
    model_family = _prompt_model_family(model)
    if model_family == "cosyvoice":
        return _build_cosyvoice_parts(context)
    if model_family == "stepaudio":
        return _build_stepaudio_parts(context)

    segment_type = context.segment_type.lower()
    if segment_type == "narration":
        return _build_narration_parts(context)
    if segment_type in {"monologue", "inner_monologue"}:
        return _build_monologue_parts(context)
    if segment_type == "dialogue":
        return _build_dialogue_parts(context)
    return _build_generic_parts(context)
