"""Model-aware TTS style-control prompt builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_25_TTS_MODEL,
    get_audiobook_tts_style_capabilities,
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


@dataclass(frozen=True)
class TTSStyleControl:
    """Normalized style-control payload before provider-specific request building."""

    mode: str
    provider_fields: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, str]] = field(default_factory=list)
    text_prefix: str = ""
    warnings: List[str] = field(default_factory=list)


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


def _coerce_string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [_text(item) for item in value]
    return []


def _build_common_parts(voice_params: Dict[str, Any], emotion: str = "neutral") -> List[str]:
    parts: List[str] = []
    segment_speaker = _text(voice_params.get("segment_speaker"))
    segment_type = _text(voice_params.get("segment_type"))
    role = _text(voice_params.get("instruct_role"))
    identity = _text(voice_params.get("instruct_identity"))
    scene = _text(voice_params.get("instruct_scene"))
    target_emotion = _text(voice_params.get("instruct_emotion")) or _text(emotion)
    performance_notes = _text(voice_params.get("performance_notes"))
    voice_description = sanitize_voice_description(voice_params.get("voice_description"))

    if voice_description:
        parts.append(f"声音描述：{voice_description}")
    if segment_speaker and segment_speaker != "旁白":
        parts.append(f"说话角色：{segment_speaker}")
    if segment_type:
        parts.append(f"片段类型：{segment_type}")
    if role:
        parts.append(f"角色设定：{role}")
    if identity:
        parts.append(f"身份设定：{identity}")
    if scene:
        parts.append(f"场景氛围：{scene}")
    if target_emotion and target_emotion != "neutral":
        parts.append(f"情绪目标：{target_emotion}")
    if performance_notes:
        parts.append(f"演绎要求：{performance_notes}")
    parts.extend(delivery_plan_instruction_parts(voice_params.get("delivery_plan")))
    return parts


def _build_common_instruction(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    explicit = _text(voice_params.get("instructions") or voice_params.get("instruction"))
    parts = _build_common_parts(voice_params, emotion)
    instruction_parts: List[str] = []
    if explicit:
        instruction_parts.append(explicit)
    instruction_parts.extend(part for part in parts if part and part not in explicit)
    return "；".join(instruction_parts).strip("；")


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
    style_tags = _unique_nonempty(_coerce_string_list(voice_params.get("style_tags")))
    delivery_plan = voice_params.get("delivery_plan") if isinstance(voice_params.get("delivery_plan"), dict) else {}
    if not style_tags:
        style_tags.extend(delivery_plan_style_tags(delivery_plan, _text(voice_params.get("instruct_emotion")) or emotion))

    inline_tags = _unique_nonempty(_coerce_string_list(voice_params.get("inline_audio_tags")))
    inline_tags.extend(tag for tag in delivery_plan_inline_tags(delivery_plan) if tag not in inline_tags)
    chunks: List[str] = []
    if style_tags:
        chunks.append(f"（{'，'.join(style_tags)}）")
    chunks.extend(f"[{tag}]" for tag in inline_tags)
    return "".join(chunks)


def _build_doubao_voice_label_prefix(voice_params: Dict[str, Any], emotion: str = "neutral") -> str:
    inline_tags = _unique_nonempty(_coerce_string_list(voice_params.get("inline_audio_tags")))
    delivery_plan = voice_params.get("delivery_plan") if isinstance(voice_params.get("delivery_plan"), dict) else {}
    inline_tags.extend(tag for tag in delivery_plan_inline_tags(delivery_plan) if tag not in inline_tags)
    if not inline_tags:
        style_tags = _unique_nonempty(_coerce_string_list(voice_params.get("style_tags")))
        style_tags.extend(tag for tag in delivery_plan_style_tags(delivery_plan, _text(voice_params.get("instruct_emotion")) or emotion) if tag not in style_tags)
        inline_tags.extend(style_tags)
    return f"[{'，'.join(inline_tags)}]" if inline_tags else ""


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
    if preferred_mode == "basic" and "natural_language" not in control_modes:
        return TTSStyleControl(mode="basic")

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
            prefix = _build_mimo_audio_tag_prefix(params, emotion)
            return TTSStyleControl(
                mode="mimo_audio_tags",
                provider_fields={"style_control_mode": "audio_tags"},
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
        instruction = _build_common_instruction(params, emotion)
        if not instruction and not params.get("use_instruct_mode"):
            return TTSStyleControl(mode="none", warnings=description_result.warnings)
        return TTSStyleControl(
            mode="stepaudio_global_context",
            provider_fields={
                "instruction": instruction,
                "style_control_mode": "global_context",
            }
            if instruction
            else {},
            warnings=description_result.warnings,
        )

    if normalized_model == SEED_TTS_20_EXPRESSIVE_MODEL or is_doubao_style_control_model(normalized_model):
        instruction = _build_common_instruction(params, emotion)
        use_labels = _style_control_method(params) in {"audio_tags", "tags", "label", "labels", "voice_labels"}
        label_prefix = _build_doubao_voice_label_prefix(params, emotion) if use_labels else ""
        if not instruction and not params.get("use_instruct_mode") and not label_prefix:
            return TTSStyleControl(mode="none", warnings=description_result.warnings)
        return TTSStyleControl(
            mode="doubao_query_response",
            provider_fields={
                "style_control_mode": "query_response",
                "context_texts": [instruction],
                "use_tag_parser": bool(label_prefix),
            }
            if instruction or label_prefix
            else {},
            text_prefix=label_prefix,
            warnings=description_result.warnings,
        )

    instruction = _build_common_instruction(params, emotion)
    if not instruction and not params.get("use_instruct_mode"):
        return TTSStyleControl(mode="none")

    return TTSStyleControl(
        mode="natural_language",
        provider_fields={
            "instructions": instruction,
            "optimize_instructions": bool(params.get("optimize_instructions", True)),
        }
        if instruction
        else {},
        warnings=description_result.warnings,
    )


def prepare_text_for_style_control(text: str, style_control: TTSStyleControl) -> str:
    prefix = _text(style_control.text_prefix)
    body = str(text or "")
    return f"{prefix}{body}" if prefix else body
