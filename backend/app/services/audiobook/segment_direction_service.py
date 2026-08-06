"""单片段工作台的供应商中立提示意图解析与用户朗读分析。"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.services.audiobook.llm_client import call_audiobook_llm_async
from app.services.audiobook.llm_json import parse_llm_json_object
from app.services.audiobook.prompt_audio_asr_provider import PromptAudioAsrProvider
from app.services.audiobook.tts_model_ids import (
    get_audiobook_tts_style_capabilities,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.voice_identity_policy import (
    sanitize_fixed_voice_performance_text,
    sanitize_fixed_voice_scene_text,
)


_VOICE_STRING_FIELDS = {
    "instruct_emotion",
    "instruct_scene",
}
_VOICE_NUMBER_FIELDS = {"pause_before", "pause_after"}
_VOICE_PARAM_NUMBER_FIELDS = {"volume"}
_PACE_VALUES = {"slow", "medium", "fast"}
_INTENSITY_VALUES = {"low", "medium", "high"}
_ENDING_VALUES = {"natural", "clipped", "lengthened"}
_SFX_LAYER_VALUES = {"bottom", "action", "atmosphere"}
_SFX_TIMING_VALUES = {"continuous", "throughout", "trigger"}
_SFX_POSITION_VALUES = {
    "left",
    "right",
    "center",
    "front",
    "back",
    "left_to_right",
    "right_to_left",
}


async def assist_segment_direction(
    *,
    cue_type: str,
    description: str,
    segment: Optional[Mapping[str, Any]],
    tts_model: Any,
    llm_client: Any = None,
) -> Dict[str, Any]:
    """将用户描述整理为受控语义补丁，不允许模型写入运行时合成字段。"""

    normalized_type = _normalize_cue_type(cue_type)
    normalized_description = str(description or "").strip()
    if not normalized_description:
        raise ValueError("description 不能为空")
    current_segment = dict(segment or {})
    model = normalize_audiobook_tts_model(tts_model, default=str(tts_model or ""))
    safe_description = normalized_description
    blocked_identity_fragments: list[str] = []
    if normalized_type == "voice":
        safe_description, blocked_identity_fragments = sanitize_fixed_voice_performance_text(
            normalized_description
        )
    rule_intent = _build_rule_intent(safe_description) if normalized_type == "voice" else {}
    raw_result: Dict[str, Any] = {}
    source = "rules"

    if llm_client is not None:
        try:
            response = await call_audiobook_llm_async(
                llm_client,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是有声小说单片段导演。只把用户要求解析成供应商中立意图和语义字段建议，"
                            "角色身份和叙事身份只能继承现有剧本配置，不得建议或改写。"
                            "不得生成音色ID、模型ID、素材ID、音频路径、delivery_plan 或供应商请求参数。"
                            "严格输出JSON对象。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": _build_llm_prompt(
                            cue_type=normalized_type,
                            description=safe_description,
                            segment=current_segment,
                            tts_model=model,
                        ),
                    },
                ],
                max_tokens=700,
                temperature=0.2,
                timeout_seconds=30,
                response_format={"type": "json_object"},
                use_cache=False,
            )
            raw_result = parse_llm_json_object(response)
            source = "llm"
        except Exception:
            raw_result = {}

    llm_intent = raw_result.get("intent") if isinstance(raw_result.get("intent"), dict) else {}
    intent = _normalize_intent({**rule_intent, **llm_intent})
    llm_patch = raw_result.get("patch") if isinstance(raw_result.get("patch"), dict) else {}
    patch = _build_semantic_patch(
        cue_type=normalized_type,
        description=safe_description,
        current_segment=current_segment,
        llm_patch=llm_patch,
        intent=intent,
    )
    capabilities = get_audiobook_tts_style_capabilities(model) if model else {}

    warnings = _build_capability_warnings(
        description=safe_description,
        intent=intent,
        capabilities=capabilities,
    )
    if blocked_identity_fragments:
        warnings.insert(0, _identity_filter_warning(blocked_identity_fragments))

    return {
        "cue_type": normalized_type,
        "description": normalized_description,
        "source": source,
        "patch": patch,
        "intent": intent,
        "model_capabilities": {
            "model": model,
            "model_family": str(capabilities.get("model_family") or "generic"),
            "style_control_modes": list(capabilities.get("style_control_modes") or []),
            "supports_audio_tags": bool(capabilities.get("supports_audio_tags")),
            "supports_word_level_control": bool(capabilities.get("supports_word_level_control")),
        },
        "warnings": warnings,
    }


async def analyze_segment_direction_reading(
    *,
    audio_bytes: bytes,
    filename: str,
    expected_text: str,
    segment: Optional[Mapping[str, Any]],
    tts_model: Any,
    provider: PromptAudioAsrProvider,
    temp_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """分析用户朗读录音：校验朗读文本一致性，并把朗读特点转为 TTS 语义指令补丁。"""

    if not audio_bytes:
        raise ValueError("录音不能为空")
    normalized_expected = str(expected_text or "").strip()
    if not normalized_expected:
        raise ValueError("片段台词为空，无法分析朗读")
    current_segment = dict(segment or {})
    model = normalize_audiobook_tts_model(tts_model, default=str(tts_model or ""))

    suffix = _safe_audio_suffix(filename)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            prefix="segment_reading_",
            dir=str(temp_dir) if temp_dir else None,
            delete=False,
        ) as handle:
            handle.write(audio_bytes)
            temp_path = Path(handle.name)
        result = await asyncio.to_thread(
            provider.transcribe,
            str(temp_path),
            instruction=_build_reading_analysis_instruction(normalized_expected),
        )
    finally:
        # 临时录音无论成功失败都立即回收
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    try:
        payload = parse_llm_json_object(str(result.transcript or ""))
    except Exception as exc:
        raise ValueError("朗读分析结果解析失败，请重新录音再试") from exc

    spoken_transcript = str(payload.get("spoken_transcript") or "").strip()
    if not bool(payload.get("text_match")):
        shown = spoken_transcript or "未识别到有效朗读内容"
        message = f"朗读内容与片段台词不一致：识别为『{shown}』，请对照文本重新朗读。"
        mismatch_detail = str(payload.get("mismatch_detail") or "").strip()
        if mismatch_detail:
            message += f"（{mismatch_detail}）"
        raise ValueError(message)

    performance_summary = str(payload.get("performance_summary") or "").strip()[:1000]
    safe_performance_summary, blocked_identity_fragments = sanitize_fixed_voice_performance_text(
        performance_summary
    )
    raw_intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    intent = _normalize_intent(raw_intent)
    llm_patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else {}
    patch = _build_semantic_patch(
        cue_type="voice",
        description=safe_performance_summary,
        current_segment=current_segment,
        llm_patch=llm_patch,
        intent=intent,
    )
    capabilities = get_audiobook_tts_style_capabilities(model) if model else {}
    warnings = _build_capability_warnings(
        description=safe_performance_summary,
        intent=intent,
        capabilities=capabilities,
    )
    if blocked_identity_fragments:
        warnings.insert(0, _identity_filter_warning(blocked_identity_fragments))

    return {
        "cue_type": "voice",
        "source": "omni_reading",
        "spoken_transcript": spoken_transcript,
        "performance_summary": safe_performance_summary,
        "provider": str(result.provider or ""),
        "model": str(result.model or ""),
        "patch": patch,
        "intent": intent,
        "model_capabilities": {
            "model": model,
            "model_family": str(capabilities.get("model_family") or "generic"),
            "style_control_modes": list(capabilities.get("style_control_modes") or []),
            "supports_audio_tags": bool(capabilities.get("supports_audio_tags")),
            "supports_word_level_control": bool(capabilities.get("supports_word_level_control")),
        },
        "warnings": warnings,
    }


def _build_reading_analysis_instruction(expected_text: str) -> str:
    return (
        "用户正在朗读下面这句有声书台词：\n"
        f"『{expected_text}』\n"
        "请以有声书导演身份完成音频理解：\n"
        "1. 逐字转写录音中实际朗读的内容，并判断它是否与上述台词一致"
        "（忽略标点、语气词和轻微口音差异；有实质内容的增删改判为不一致）；\n"
        "2. 只分析可迁移的表演特点：语速、语势、强弱、情绪、重音词、停顿、"
        "断句、呼吸与句尾处理。\n"
        "只输出一个JSON对象，不要解释、不要代码块："
        '{"text_match": true或false, "spoken_transcript": "实际朗读的逐字内容", '
        '"mismatch_detail": "不一致原因，一致时为空字符串", '
        '"performance_summary": "一句简洁中文描述朗读特点", '
        '"intent": {"pace":"slow|medium|fast","intensity":"low|medium|high",'
        '"emotion_primary":"neutral|happy|sad|angry|fearful|surprised|disgusted",'
        '"stress_words":[],'
        '"ending_style":"natural|clipped|lengthened"},'
        '"patch": {"instruct_emotion":"情绪","instruct_scene":"场景",'
        '"pause_before":0.0,"pause_after":0.0,"voice_params":{'
        '"volume":50.0}}}。'
        "不得输出 pitch、pitch_ratio 或 pitch_semitones；"
        "intent 与 patch 只填能从音频中判断的表演字段；"
        "不得推断或描述性别、年龄感、基础声线或音色身份；"
        "不得输出任何性别、年龄、说话人身份转换、模仿对象或永久音色质感；"
        "生病、受伤等特殊状态下的沙哑只能描述为在原音色基础上的轻微短暂状态；"
        "不得输出或改写角色身份、叙事身份、音色ID、模型ID或素材路径。"
    )


def _normalize_cue_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"voice", "sfx", "bgm"}:
        raise ValueError(f"不支持的提示类型: {normalized or 'empty'}")
    return normalized


def _build_llm_prompt(
    *, cue_type: str,
    description: str,
    segment: Mapping[str, Any],
    tts_model: str,
) -> str:
    context = {
        key: segment.get(key)
        for key in (
            "type",
            "speaker",
            "emotion",
            "text",
            "original_text",
            "instruct_emotion",
            "instruct_scene",
        )
        if segment.get(key) not in (None, "", [], {})
    }
    if cue_type == "sfx":
        output_contract = (
            '{"intent":{},"patch":{"sound_effects":[{'
            '"name":"简短音效名","layer":"bottom|action|atmosphere",'
            '"volume":0.0,"timing":"continuous|throughout|trigger",'
            '"position_3d":"left|right|center|front|back|left_to_right|right_to_left",'
            '"duration":0.0,"fade_in":0.0,"fade_out":0.0,"delay":0.0}]}}。'
            "只补全描述能够支持的字段；不得输出 asset_id、file、audio_file 或路径。"
        )
    elif cue_type == "bgm":
        output_contract = (
            '{"intent":{},"patch":{"music_cue":{'
            '"style":"简短配乐风格","mood":"情绪",'
            '"volume":0.0,"fade_in":0.0,"fade_out":0.0,'
            '"duration":0.0,"start_time":0.0,"emotion_follow":true}}}。'
            "只补全描述能够支持的字段；不得输出 asset_id、file、audio_file 或路径。"
        )
    else:
        output_contract = (
            '{"intent":{"pace":"slow|medium|fast",'
            '"intensity":"low|medium|high",'
            '"emotion_primary":"neutral|happy|sad|angry|fearful|surprised|disgusted",'
            '"stress_words":[],'
            '"ending_style":"natural|clipped|lengthened"},"patch":{'
            '"instruct_emotion":"情绪","instruct_scene":"场景",'
            '"pause_before":0.0,"pause_after":0.0,"voice_params":{'
            '"volume":50.0}}}。'
            "不得输出 pitch、pitch_ratio 或 pitch_semitones；"
            "patch 只建议用户未提供的表演语义字段；角色身份和叙事身份只能继承现有配置；"
            "不得推断或描述性别、年龄感、基础声线或音色身份；"
            "不得建议任何性别、年龄、说话人身份转换、变声、换声或永久音色质感；"
            "病伤等特殊状态下的沙哑只能写成在原音色基础上的轻微短暂状态；"
            "不得输出 speaker、tts_model、素材身份或运行时字段。"
        )
    return (
        f"提示类型：{cue_type}\n"
        f"TTS模型：{tts_model or '未指定'}\n"
        f"片段上下文：{json.dumps(context, ensure_ascii=False)}\n"
        f"用户描述：{description}\n"
        f"返回结构：{output_contract}"
    )


def _build_rule_intent(description: str) -> Dict[str, Any]:
    intent: Dict[str, Any] = {}
    if _contains_any(description, ("缓慢", "慢速", "放慢", "偏慢")):
        intent["pace"] = "slow"
    elif _contains_any(description, ("快速", "加快", "偏快", "急促")):
        intent["pace"] = "fast"
    emotion = _infer_emotion(description)
    if emotion:
        intent["emotion_primary"] = emotion
    stress_words = _extract_stress_words(description)
    if stress_words:
        intent["stress_words"] = stress_words
    if _contains_any(description, ("句尾拖长", "尾音拖长", "尾音拉长", "结尾拖长")):
        intent["ending_style"] = "lengthened"
    elif _contains_any(description, ("句尾收紧", "短促收尾", "干脆收尾")):
        intent["ending_style"] = "clipped"
    return intent


def _normalize_intent(value: Mapping[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for key, allowed in (
        ("pace", _PACE_VALUES),
        ("intensity", _INTENSITY_VALUES),
        ("ending_style", _ENDING_VALUES),
    ):
        normalized = str(value.get(key) or "").strip().lower()
        if normalized in allowed:
            output[key] = normalized
    emotion = str(value.get("emotion_primary") or "").strip().lower()
    if emotion in {"neutral", "happy", "sad", "angry", "fearful", "surprised", "disgusted"}:
        output["emotion_primary"] = emotion
    for key in ("stress_words",):
        items = value.get(key)
        if not isinstance(items, (list, tuple)):
            continue
        normalized_items = []
        for item in items[:8]:
            text = str(item or "").strip()[:24]
            if text and text not in normalized_items:
                normalized_items.append(text)
        if normalized_items:
            output[key] = normalized_items
    return output


def _build_semantic_patch(
    *,
    cue_type: str,
    description: str,
    current_segment: Mapping[str, Any],
    llm_patch: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> Dict[str, Any]:
    if cue_type == "sfx":
        effects = _normalize_sound_effects_patch(
            description=description,
            current_segment=current_segment,
            llm_patch=llm_patch,
        )
        if effects:
            return {"sound_effects": effects, "sound_effects_simple": []}
        return {"sound_effects_simple": [description]}
    if cue_type == "bgm":
        music_cue = _normalize_music_cue_patch(
            current_segment=current_segment,
            llm_patch=llm_patch,
        )
        if music_cue:
            return {"music_cue": music_cue, "music_cue_simple": None}
        return {"music_cue_simple": description}

    patch: Dict[str, Any] = {}
    if description:
        patch["performance_notes"] = description
    for key in _VOICE_STRING_FIELDS:
        if _has_user_value(current_segment.get(key), allow_neutral_default=key == "instruct_emotion"):
            continue
        value = str(llm_patch.get(key) or "").strip()[:240]
        if key == "instruct_scene":
            value, _ = sanitize_fixed_voice_scene_text(value)
        elif key == "instruct_emotion":
            value, _ = sanitize_fixed_voice_performance_text(value)
        if not value and key == "instruct_emotion":
            value = str(intent.get("emotion_primary") or "").strip()
        if value:
            patch[key] = value
    for key in _VOICE_NUMBER_FIELDS:
        if _has_user_value(current_segment.get(key)):
            continue
        value = _bounded_number(llm_patch.get(key), minimum=0, maximum=10)
        if value is not None:
            patch[key] = value

    current_voice_params = current_segment.get("voice_params")
    current_voice_params = current_voice_params if isinstance(current_voice_params, Mapping) else {}
    suggested_voice_params = llm_patch.get("voice_params")
    suggested_voice_params = suggested_voice_params if isinstance(suggested_voice_params, Mapping) else {}
    voice_param_patch: Dict[str, float] = {}
    for key in _VOICE_PARAM_NUMBER_FIELDS:
        if _has_user_value(current_voice_params.get(key)):
            continue
        bounds = (0.5, 2.0) if key != "volume" else (0, 100)
        value = _bounded_number(suggested_voice_params.get(key), minimum=bounds[0], maximum=bounds[1])
        if value is not None:
            voice_param_patch[key] = value
    if voice_param_patch:
        patch["voice_params"] = voice_param_patch
    return patch


def _normalize_sound_effects_patch(
    *,
    description: str,
    current_segment: Mapping[str, Any],
    llm_patch: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    raw_suggestions = llm_patch.get("sound_effects")
    if not isinstance(raw_suggestions, list):
        return []

    current_effects = current_segment.get("sound_effects")
    current_effects = current_effects if isinstance(current_effects, list) else []
    output: list[Dict[str, Any]] = []
    for index, raw_suggestion in enumerate(raw_suggestions[:8]):
        if not isinstance(raw_suggestion, Mapping):
            continue
        suggestion = _normalize_sound_effect_item(raw_suggestion)
        if index == 0 and not suggestion.get("name"):
            suggestion["name"] = description[:240]

        # 素材身份与用户已填写参数只从当前片段继承，绝不接受 LLM 生成。
        if index < len(current_effects) and isinstance(current_effects[index], Mapping):
            current = _normalize_sound_effect_item(current_effects[index])
            for identity_key in ("asset_id", "id", "effect_id"):
                identity = _bounded_text(current_effects[index].get(identity_key), 160)
                if identity:
                    current[identity_key] = identity
            suggestion.update(current)
        if suggestion.get("name") or any(
            suggestion.get(key) for key in ("asset_id", "id", "effect_id")
        ):
            output.append(suggestion)

    for raw_current in current_effects[len(raw_suggestions[:8]) : 8]:
        if not isinstance(raw_current, Mapping):
            continue
        current = _normalize_sound_effect_item(raw_current)
        for identity_key in ("asset_id", "id", "effect_id"):
            identity = _bounded_text(raw_current.get(identity_key), 160)
            if identity:
                current[identity_key] = identity
        if current.get("name") or any(
            current.get(key) for key in ("asset_id", "id", "effect_id")
        ):
            output.append(current)
    return output


def _normalize_sound_effect_item(value: Mapping[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    name = _bounded_text(value.get("name"), 240)
    if name:
        output["name"] = name
    for key, allowed in (
        ("layer", _SFX_LAYER_VALUES),
        ("timing", _SFX_TIMING_VALUES),
        ("position_3d", _SFX_POSITION_VALUES),
    ):
        normalized = str(value.get(key) or "").strip().lower()
        if normalized in allowed:
            output[key] = normalized
    for key, maximum in (
        ("volume", 1),
        ("duration", 600),
        ("fade_in", 60),
        ("fade_out", 60),
        ("delay", 600),
    ):
        number = _bounded_number(value.get(key), minimum=0, maximum=maximum)
        if number is not None:
            output[key] = number
    return output


def _normalize_music_cue_patch(
    *,
    current_segment: Mapping[str, Any],
    llm_patch: Mapping[str, Any],
) -> Dict[str, Any]:
    raw_suggestion = llm_patch.get("music_cue")
    if not isinstance(raw_suggestion, Mapping):
        return {}
    output = _normalize_music_cue_item(raw_suggestion)

    current_cue = current_segment.get("music_cue")
    if isinstance(current_cue, Mapping):
        # 数值/时序等用户已有值优先；style、mood 可按本次描述重新整理。
        current = _normalize_music_cue_item(current_cue)
        for key in (
            "volume",
            "fade_in",
            "fade_out",
            "duration",
            "start_time",
            "emotion_follow",
        ):
            if key in current:
                output[key] = current[key]
        for identity_key in ("asset_id", "id", "music_id", "name"):
            identity = _bounded_text(current_cue.get(identity_key), 160)
            if identity:
                output[identity_key] = identity
    return output


def _normalize_music_cue_item(value: Mapping[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for key, maximum_length in (("style", 240), ("mood", 80)):
        text = _bounded_text(value.get(key), maximum_length)
        if text:
            output[key] = text
    for key, maximum in (
        ("volume", 1),
        ("fade_in", 60),
        ("fade_out", 60),
        ("duration", 3600),
        ("start_time", 3600),
    ):
        number = _bounded_number(value.get(key), minimum=0, maximum=maximum)
        if number is not None:
            output[key] = number
    if isinstance(value.get("emotion_follow"), bool):
        output["emotion_follow"] = value["emotion_follow"]
    return output


def _build_capability_warnings(
    *,
    description: str,
    intent: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if intent.get("stress_words") and not capabilities.get("supports_word_level_control"):
        warnings.append("当前模型不保证逐词重读控制，系统将降级为自然语言导演提示。")
    if intent.get("ending_style") == "lengthened" and not capabilities.get("supports_word_level_control"):
        warnings.append("当前模型不保证精确尾音时长，句尾拖长将作为自然语言偏好传递。")
    return warnings


def _identity_filter_warning(fragments: list[str]) -> str:
    return (
        "已忽略可能改变已选音色身份、年龄感或基础声线的描述："
        + "、".join(fragments)
        + "。只保留当前片段的表演方式。"
    )


def _extract_stress_words(description: str) -> list[str]:
    patterns = (
        r"(?:重读|强调|加重)\s*[\"'“‘]?([^\"'”’\s，。！？；：]{1,12})[\"'”’]?\s*字?",
        r"[\"'“‘]([^\"'”’]{1,12})[\"'”’]\s*字?\s*(?:重读|强调|加重)",
    )
    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, description):
            value = match.group(1).strip()
            if value and value not in values:
                values.append(value)
    return values[:8]


def _infer_emotion(description: str) -> str:
    for emotion, keywords in (
        ("sad", ("痛苦", "悲伤", "哽咽", "绝望")),
        ("angry", ("愤怒", "怒吼", "生气")),
        ("fearful", ("恐惧", "害怕", "惊慌", "紧张")),
        ("happy", ("开心", "喜悦", "兴奋")),
        ("surprised", ("惊讶", "震惊")),
        ("disgusted", ("厌恶", "嫌恶")),
    ):
        if _contains_any(description, keywords):
            return emotion
    return ""


def _has_user_value(value: Any, *, allow_neutral_default: bool = False) -> bool:
    if value in (None, "", [], {}):
        return False
    if allow_neutral_default and str(value).strip().lower() == "neutral":
        return False
    return True


def _bounded_number(value: Any, *, minimum: float, maximum: float) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < minimum or number > maximum:
        return None
    return number


def _bounded_text(value: Any, maximum_length: int) -> str:
    return str(value or "").strip()[:maximum_length]


def _safe_audio_suffix(filename: str) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    return suffix if suffix in {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"} else ".webm"


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)
