"""Model-aware TTS style-control prompt builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_25_TTS_MODEL,
    get_audiobook_tts_style_capabilities,
    normalize_audiobook_tts_emotion,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.voice_description_policy import (
    reconcile_voice_description_with_selected_voice,
    sanitize_voice_description,
)
from app.services.audiobook.tts_delivery_plan import (
    build_delivery_plan,
    delivery_plan_inline_tags,
    delivery_plan_instruction_parts,
    delivery_plan_style_tags,
)
from app.services.audiobook.tts_prompt_strategy import (
    build_common_prompt_parts,
    compact_instruction_parts,
    measure_cosyvoice_instruction_units,
    render_stepaudio_inline_prefix,
    truncate_cosyvoice_instruction_units,
)


@dataclass(frozen=True)
class TTSStyleControl:
    """Normalized style-control payload before provider-specific request building."""

    mode: str
    provider_fields: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, str]] = field(default_factory=list)
    text_prefix: str = ""
    warnings: List[str] = field(default_factory=list)
    budget: Dict[str, Any] = field(default_factory=dict)


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
    delivery_plan_parts: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class _InlineTagStrategy:
    model_family: str
    placement: str
    style_tags: List[str] = field(default_factory=list)
    inline_tags: List[str] = field(default_factory=list)
    use_tag_parser: bool = False

    def to_provider_field(self) -> Dict[str, Any]:
        return {
            "model_family": self.model_family,
            "placement": self.placement,
            "style_tags": list(self.style_tags),
            "inline_tags": list(self.inline_tags),
            "use_tag_parser": self.use_tag_parser,
        }


def is_mimo_style_control_model(model: Any) -> bool:
    return get_audiobook_tts_style_capabilities(model).get("model_family") == "mimo"


def is_stepaudio_style_control_model(model: Any) -> bool:
    return get_audiobook_tts_style_capabilities(model).get("model_family") == "stepaudio"


def is_doubao_style_control_model(model: Any) -> bool:
    return get_audiobook_tts_style_capabilities(model).get("model_family") == "doubao"


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


def _compact_instruction_parts(
    parts: List[str],
    budget: int | None,
) -> tuple[str, Dict[str, Any], List[str]]:
    return compact_instruction_parts(parts, budget)


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


def _build_stepaudio_inline_prefix(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    return render_stepaudio_inline_prefix(voice_params, emotion)


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
        target_emotion = normalize_emotion_for_model(target_emotion, model)
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


def normalize_emotion_for_model(emotion: Any, model: Any) -> str:
    """Normalize emotion labels according to the selected model capability matrix."""

    return normalize_audiobook_tts_emotion(emotion, model)


def _build_common_parts(
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
    *,
    model: Any = None,
) -> List[str]:
    return build_common_prompt_parts(voice_params, emotion, model=model)


def _build_common_instruction(
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
    *,
    model: Any = None,
    budget: int | None = None,
) -> tuple[str, Dict[str, Any], List[str]]:
    explicit = _text(voice_params.get("instructions") or voice_params.get("instruction"))
    parts = _build_common_parts(voice_params, emotion, model=model)
    instruction_parts: List[str] = []
    model_family = get_audiobook_tts_style_capabilities(model).get("model_family")
    if model_family == "cosyvoice":
        instruction_parts.extend(part for part in parts if part and part not in explicit)
        if explicit:
            instruction_parts.append(explicit)
        return compact_instruction_parts(
            instruction_parts,
            budget,
            measure_text=measure_cosyvoice_instruction_units,
            truncate_text=truncate_cosyvoice_instruction_units,
        )
    if model_family == "stepaudio" and not explicit and budget:
        priority_parts = [part for part in parts if part and not part.startswith("声音描述：")]
        voice_parts = [part for part in parts if part.startswith("声音描述：")]
        instruction, budget_payload, warnings = _compact_instruction_parts(priority_parts, budget)
        if not voice_parts:
            return instruction, budget_payload, warnings

        used = len(instruction)
        fitting_voice_parts: List[str] = []
        dropped_voice_parts: List[str] = []
        for part in voice_parts:
            delimiter_cost = 1 if instruction or fitting_voice_parts else 0
            if used + delimiter_cost + len(part) <= budget:
                fitting_voice_parts.append(part)
                used += delimiter_cost + len(part)
            else:
                dropped_voice_parts.append(part)

        if fitting_voice_parts:
            instruction, budget_payload, warnings = _compact_instruction_parts(
                [*priority_parts, *fitting_voice_parts],
                budget,
            )
        if dropped_voice_parts:
            budget_payload = dict(budget_payload or {})
            dropped_fields = list(budget_payload.get("dropped_fields") or [])
            dropped_fields.extend(dropped_voice_parts)
            budget_payload.update(
                {
                    "limit": budget,
                    "used": len(instruction),
                    "truncated": True,
                    "dropped_fields": dropped_fields,
                }
            )
            warnings = [f"instruction 已按 {budget} 字预算压缩"]
        return instruction, budget_payload, warnings
    if explicit:
        instruction_parts.append(explicit)
    instruction_parts.extend(part for part in parts if part and part not in explicit)
    return _compact_instruction_parts(instruction_parts, budget)


def _build_mimo_director_prompt(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    explicit = _text(voice_params.get("instructions") or voice_params.get("instruction"))
    role = _text(voice_params.get("instruct_role") or voice_params.get("instruct_identity"))
    segment_speaker = _text(voice_params.get("segment_speaker"))
    scene = _text(voice_params.get("instruct_scene"))
    target_emotion = _text(voice_params.get("instruct_emotion")) or _text(emotion)
    performance_notes = _text(voice_params.get("performance_notes"))
    voice_description = sanitize_voice_description(voice_params.get("voice_description"))
    delivery_plan = voice_params.get("delivery_plan") if isinstance(voice_params.get("delivery_plan"), dict) else {}

    role_text = (
        _text(delivery_plan.get("director_role"))
        or role
        or (f"{segment_speaker}，有声书角色" if segment_speaker and segment_speaker != "旁白" else "有声书旁白")
    )
    scene_text = _text(delivery_plan.get("director_scene")) or scene or "根据当前有声书片段的上下文进行自然演绎。"
    guidance_parts = _unique_nonempty([
        voice_description,
        explicit,
        target_emotion if target_emotion != "neutral" else "",
        performance_notes,
        *delivery_plan_instruction_parts(delivery_plan),
    ])
    guidance = "；".join(guidance_parts) or "保持自然、清晰、贴合角色与场景。"

    return f"角色：{role_text}\n场景：{scene_text}\n指导：{guidance}"


def _build_mimo_voice_design_prompt(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    explicit_design = _text(voice_params.get("voice_design_prompt"))
    explicit_instruction = _text(voice_params.get("instructions") or voice_params.get("instruction"))
    voice_description = sanitize_voice_description(voice_params.get("voice_description"))
    parts = [
        part
        for part in _build_common_parts(voice_params, emotion)
        if part and not part.startswith("声音描述：")
    ]

    prompt_parts: List[str] = []
    if explicit_design:
        prompt_parts.append(explicit_design)
    if voice_description and voice_description not in explicit_design:
        prompt_parts.append(voice_description)
    if explicit_instruction:
        prompt_parts.append(explicit_instruction)
    prompt_parts.extend(part for part in parts if part and part not in explicit_design and part not in explicit_instruction)
    return "；".join(_unique_nonempty(prompt_parts)).strip("；")


def _build_mimo_audio_tag_prefix(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    strategy = _build_inline_tag_strategy(
        "mimo",
        voice_params,
        emotion,
        placement="assistant_prefix",
    )
    return _render_mimo_audio_tag_prefix(strategy)


def _build_doubao_voice_label_prefix(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    strategy = _build_inline_tag_strategy(
        "doubao",
        voice_params,
        emotion,
        placement="text_prefix",
        use_tag_parser=True,
    )
    return _render_doubao_voice_label_prefix(strategy)


def _build_inline_tag_strategy(
    model_family: str,
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
    *,
    placement: str,
    use_tag_parser: bool = False,
) -> _InlineTagStrategy:
    delivery_plan = voice_params.get("delivery_plan") if isinstance(voice_params.get("delivery_plan"), dict) else {}
    style_tags = _unique_nonempty(_coerce_string_list(voice_params.get("style_tags")))
    fallback_style_tags = delivery_plan_style_tags(delivery_plan, _text(voice_params.get("instruct_emotion")) or emotion)
    inline_tags = _unique_nonempty(_coerce_string_list(voice_params.get("inline_audio_tags")))
    inline_tags.extend(tag for tag in delivery_plan_inline_tags(delivery_plan) if tag not in inline_tags)
    if not style_tags:
        style_tags.extend(fallback_style_tags)
    elif model_family == "doubao" and not inline_tags:
        style_tags.extend(tag for tag in fallback_style_tags if tag not in style_tags)
    return _InlineTagStrategy(
        model_family=model_family,
        placement=placement,
        style_tags=style_tags,
        inline_tags=inline_tags,
        use_tag_parser=use_tag_parser,
    )


def _render_mimo_audio_tag_prefix(strategy: _InlineTagStrategy) -> str:
    chunks: List[str] = []
    if strategy.style_tags:
        chunks.append(f"（{'，'.join(strategy.style_tags)}）")
    chunks.extend(f"[{tag}]" for tag in strategy.inline_tags)
    return "".join(chunks)


def _render_doubao_voice_label_prefix(strategy: _InlineTagStrategy) -> str:
    inline_tags = strategy.inline_tags or strategy.style_tags
    return f"[{'，'.join(inline_tags)}]" if inline_tags else ""


def _coerce_basic_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_basic_voice_settings(
    voice_params: Dict[str, Any],
) -> tuple[Dict[str, Any], List[str]]:
    delivery_plan = voice_params.get("delivery_plan") if isinstance(voice_params.get("delivery_plan"), dict) else {}
    if not delivery_plan:
        return {}, []

    speed = _coerce_basic_float(voice_params.get("rate", voice_params.get("speed")), 1.0)
    volume = _coerce_basic_float(voice_params.get("volume"), 50.0)
    pitch = _coerce_basic_float(voice_params.get("pitch"), 0.0)

    pace = _text(delivery_plan.get("pace")).lower()
    if pace == "slow":
        speed *= 0.9
    elif pace == "fast":
        speed *= 1.1

    pitch_hint = _text(delivery_plan.get("pitch")).lower()
    if pitch_hint == "lower":
        pitch -= 8
    elif pitch_hint == "higher":
        pitch += 8

    intensity = _text(delivery_plan.get("intensity")).lower()
    if intensity == "high":
        volume += 8
    elif intensity == "low":
        volume -= 6

    settings = {
        "speed": round(max(0.5, min(2.0, speed)), 2),
        "volume": int(round(max(0, min(100, volume)))),
        "pitch": int(round(max(-100, min(100, pitch)))),
    }

    warnings = ["MiniMax basic 模式不支持自然语言/标签风格控制，已降级为 speed/volume/pitch 基础参数"]
    unsupported_fields = [
        field_name
        for field_name in (
            "delivery_mode",
            "emotion_mix",
            "micro_tags",
            "pause_strategy",
            "stress_words",
            "director_guidance",
            "style_instruction",
        )
        if delivery_plan.get(field_name)
    ]
    if unsupported_fields:
        warnings.append("MiniMax basic 模式忽略高级 delivery_plan 字段：" + "、".join(unsupported_fields))
    return {"basic_voice_settings": settings}, warnings


def _style_control_method(voice_params: Dict[str, Any]) -> str:
    return _text(
        voice_params.get("style_control_method")
        or voice_params.get("style_control_mode")
        or voice_params.get("control_method")
    ).lower()


def build_model_style_control(
    model: Any,
    voice_params: Dict[str, Any],
    emotion: str = "neutral",
) -> TTSStyleControl:
    """Build style-control data in the format preferred by the selected TTS model."""

    params = dict(voice_params or {})
    normalized_model = normalize_audiobook_tts_model(model, default=str(model or ""))
    capabilities = get_audiobook_tts_style_capabilities(normalized_model)
    control_modes = set(_coerce_string_list(capabilities.get("style_control_modes")))
    preferred_mode = _text(capabilities.get("preferred_style_control_mode"))
    instruction_budget = capabilities.get("instruction_budget")
    if isinstance(instruction_budget, int):
        budget_value: int | None = instruction_budget
    else:
        budget_value = None
    if preferred_mode == "basic" and "natural_language" not in control_modes:
        if isinstance(params.get("delivery_plan"), dict):
            params["delivery_plan"] = build_delivery_plan(
                voice_params=params,
                model=normalized_model,
                emotion=params.get("instruct_emotion") or emotion,
            )
        provider_fields, warnings = _build_basic_voice_settings(params)
        return TTSStyleControl(
            mode="basic",
            provider_fields=provider_fields,
            warnings=warnings,
        )

    if isinstance(params.get("delivery_plan"), dict):
        params["delivery_plan"] = build_delivery_plan(
            voice_params=params,
            model=normalized_model,
            emotion=params.get("instruct_emotion") or emotion,
        )
    selected_voice = params.get("voice") or params.get("speaker")
    segment_type = _text(params.get("segment_type")).lower()
    fallback_use_case = "有声书旁白" if segment_type == "narration" else "有声书角色对白"
    description_result = reconcile_voice_description_with_selected_voice(
        model=normalized_model,
        voice_id=selected_voice,
        requested_description=params.get("voice_description"),
        fallback_emotion=params.get("instruct_emotion") or emotion,
        fallback_use_case=fallback_use_case,
    )
    if description_result.description:
        params["voice_description"] = description_result.description

    if is_mimo_style_control_model(normalized_model):
        if normalized_model == MIMO_V25_TTS_VOICE_DESIGN_MODEL:
            prompt = _build_mimo_voice_design_prompt(params, emotion)
            return TTSStyleControl(
                mode="mimo_voice_design",
                provider_fields={"style_control_mode": "voice_design"},
                messages=[{"role": "user", "content": prompt}] if prompt else [],
                warnings=description_result.warnings,
            )

        if _style_control_method(params) in {"audio_tags", "tags", "label", "labels"}:
            tag_strategy = _build_inline_tag_strategy(
                "mimo",
                params,
                emotion,
                placement="assistant_prefix",
            )
            prefix = _render_mimo_audio_tag_prefix(tag_strategy)
            return TTSStyleControl(
                mode="mimo_audio_tags",
                provider_fields={
                    "style_control_mode": "audio_tags",
                    "inline_tag_strategy": tag_strategy.to_provider_field(),
                },
                messages=[{"role": "assistant", "content": prefix}] if prefix else [],
                text_prefix=prefix,
                warnings=description_result.warnings,
            )

        prompt = _build_mimo_director_prompt(params, emotion)
        return TTSStyleControl(
            mode="mimo_director",
            provider_fields={"style_control_mode": "natural_language"},
            messages=[{"role": "user", "content": prompt}] if prompt else [],
            warnings=description_result.warnings,
        )

    if normalized_model == STEPAUDIO_25_TTS_MODEL or is_stepaudio_style_control_model(normalized_model):
        instruction, budget, budget_warnings = _build_common_instruction(
            params,
            emotion,
            model=normalized_model,
            budget=budget_value,
        )
        text_prefix = _build_stepaudio_inline_prefix(params, emotion)
        warnings = [*description_result.warnings, *budget_warnings]
        if not instruction and not text_prefix and not params.get("use_instruct_mode"):
            return TTSStyleControl(mode="none", warnings=warnings, budget=budget)
        return TTSStyleControl(
            mode="stepaudio_global_context",
            provider_fields={
                "instruction": instruction,
                "style_control_mode": "global_context",
            }
            if instruction
            else {},
            text_prefix=text_prefix,
            warnings=warnings,
            budget=budget,
        )

    if normalized_model == SEED_TTS_20_EXPRESSIVE_MODEL or is_doubao_style_control_model(normalized_model):
        instruction, budget, budget_warnings = _build_common_instruction(
            params,
            emotion,
            model=normalized_model,
            budget=budget_value,
        )
        use_labels = _style_control_method(params) in {"audio_tags", "tags", "label", "labels", "voice_labels"}
        tag_strategy = (
            _build_inline_tag_strategy(
                "doubao",
                params,
                emotion,
                placement="text_prefix",
                use_tag_parser=True,
            )
            if use_labels
            else None
        )
        label_prefix = _render_doubao_voice_label_prefix(tag_strategy) if tag_strategy else ""
        warnings = [*description_result.warnings, *budget_warnings]
        if not instruction and not params.get("use_instruct_mode") and not label_prefix:
            return TTSStyleControl(mode="none", warnings=warnings, budget=budget)
        provider_fields = {}
        if instruction or label_prefix:
            provider_fields = {
                "style_control_mode": "query_response",
                "context_texts": [instruction],
                "use_tag_parser": bool(label_prefix),
            }
            if tag_strategy:
                provider_fields["inline_tag_strategy"] = tag_strategy.to_provider_field()
        return TTSStyleControl(
            mode="doubao_query_response",
            provider_fields=provider_fields,
            text_prefix=label_prefix,
            warnings=warnings,
            budget=budget,
        )

    instruction, budget, budget_warnings = _build_common_instruction(
        params,
        emotion,
        model=normalized_model,
        budget=budget_value,
    )
    warnings = [*description_result.warnings, *budget_warnings]
    if not instruction and not params.get("use_instruct_mode"):
        return TTSStyleControl(mode="none", warnings=warnings, budget=budget)

    return TTSStyleControl(
        mode="natural_language",
        provider_fields={
            "instructions": instruction,
            "optimize_instructions": bool(params.get("optimize_instructions", True)),
        }
        if instruction
        else {},
        warnings=warnings,
        budget=budget,
    )


def prepare_text_for_style_control(text: str, style_control: TTSStyleControl) -> str:
    prefix = _text(style_control.text_prefix)
    body = str(text or "")
    if prefix and body.startswith(prefix):
        return body
    return f"{prefix}{body}" if prefix else body


def build_provider_prompt_snapshot(
    *,
    model: Any,
    voice_id: Any = "",
    style_control: TTSStyleControl,
    delivery_plan: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build an audit-friendly snapshot of the final provider prompt surface."""

    normalized_model = normalize_audiobook_tts_model(model, default=str(model or ""))
    capabilities = get_audiobook_tts_style_capabilities(normalized_model)
    provider_fields = dict(style_control.provider_fields or {})
    instructions = _text(
        provider_fields.get("instructions")
        or provider_fields.get("instruction")
    )
    context_texts = provider_fields.get("context_texts")
    if isinstance(context_texts, str):
        normalized_context_texts = [context_texts] if context_texts.strip() else []
    elif isinstance(context_texts, list):
        normalized_context_texts = [_text(item) for item in context_texts if _text(item)]
    else:
        normalized_context_texts = []
    inline_tag_strategy = provider_fields.get("inline_tag_strategy")
    normalized_inline_tag_strategy = dict(inline_tag_strategy) if isinstance(inline_tag_strategy, dict) else {}

    budget = dict(style_control.budget or {})
    if not budget:
        raw_limit = capabilities.get("instruction_budget")
        budget = {
            "limit": raw_limit if isinstance(raw_limit, int) else None,
            "used": _measure_text(instructions),
            "truncated": False,
            "dropped_fields": [],
        }
    else:
        budget.setdefault("used", _measure_text(instructions))
        budget.setdefault("truncated", False)
        budget.setdefault("dropped_fields", [])

    provider_prompt: Dict[str, Any] = {
        "instructions": instructions,
        "messages": list(style_control.messages or []),
        "text_prefix": _text(style_control.text_prefix),
        "context_texts": normalized_context_texts,
    }
    if normalized_inline_tag_strategy:
        provider_prompt["inline_tag_strategy"] = normalized_inline_tag_strategy

    return {
        "model": normalized_model,
        "voice_id": _text(voice_id),
        "mode": style_control.mode,
        "delivery_plan": dict(delivery_plan or {}),
        "provider_prompt": provider_prompt,
        "budget": budget,
        "warnings": list(style_control.warnings or []),
    }
