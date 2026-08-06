"""Build immutable, server-owned synthesis contracts for workbench candidates."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, Dict, Mapping, Optional

from app.services.audiobook.chapter_segment_assets import SERVER_MANAGED_SEGMENT_ASSET_FIELDS
from app.services.audiobook import mimo_voice_assets
from app.services.audiobook.tts_delivery_plan import build_delivery_plan
from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.tts_style_control import (
    build_model_style_control,
    build_provider_prompt_snapshot,
)
from app.services.audiobook.voice_parameter_policy import (
    stabilize_fixed_voice_pitch,
    stabilize_instruct_model_speed,
)
from app.services.audiobook.voice_identity_policy import (
    VOICE_IDENTITY_POLICY_VERSION,
    is_voice_design_creation_request,
    sanitize_fixed_voice_prompt_params,
)


CONTRACT_VERSION = 2
CANDIDATE_CONTRACT_REVISION = f"{CONTRACT_VERSION}:{VOICE_IDENTITY_POLICY_VERSION}"

SERVER_OWNED_VOICE_ASSET_PARAM_FIELDS = frozenset(
    {
        "mimo_voice_asset_id",
        "voice_design_prompt",
    }
)

CLIENT_FORBIDDEN_VOICE_ASSET_PARAM_FIELDS = frozenset(
    {
        "voice_clone_data_url",
        "voice_description",
        "voice_design_prompt",
    }
)

CLIENT_FORBIDDEN_VOICE_IDENTITY_CONTROL_FIELDS = frozenset(
    {
        "character_base_pitch",
        "pitch",
        "pitch_ratio",
        "pitch_semitones",
        *CLIENT_FORBIDDEN_VOICE_ASSET_PARAM_FIELDS,
    }
)

# These fields are compiled by the server from durable segment intent. Accepting
# a client snapshot would let stale/provider-specific data override new edits.
DERIVED_VOICE_PARAM_FIELDS = frozenset(
    {
        "audio_tags",
        "cadence_profile",
        "cadence_reason",
        "context_texts",
        "delivery_plan",
        "emotion",
        "inline_tags",
        "inline_tag_strategy",
        "instruction",
        "instruct_emotion",
        "instruct_identity",
        "instruct_role",
        "instruct_scene",
        "instructions",
        "messages",
        "performance_notes",
        "provider_fields",
        "provider_prompt",
        "provider_prompt_snapshot",
        "resolved_tts_model",
        "segment_speaker",
        "segment_type",
        "style_tags",
        "style_control_method",
        "style_control_mode",
        "control_method",
        "style_instruction",
        "text_prefix",
        "timeline_boundary_managed",
        "timeline_pause_after_ms",
        "use_tag_parser",
        "use_instruct_mode",
        *CLIENT_FORBIDDEN_VOICE_ASSET_PARAM_FIELDS,
    }
)

# Provider-facing render products must never survive a semantic edit. Runtime
# cadence fields are intentionally absent: the chapter mixer owns those values.
PROVIDER_PROMPT_DERIVED_FIELDS = frozenset(
    {
        "audio_tags",
        "context_texts",
        "delivery_plan",
        "inline_tag_strategy",
        "inline_tags",
        "instruction",
        "instructions",
        "messages",
        "provider_fields",
        "provider_prompt",
        "provider_prompt_snapshot",
        "style_instruction",
        "style_tags",
        "style_control_method",
        "style_control_mode",
        "control_method",
        "text_prefix",
        "use_tag_parser",
    }
)

_FINGERPRINT_EXCLUDED_FIELDS = set(SERVER_MANAGED_SEGMENT_ASSET_FIELDS) | {
    # 片段稳定身份用于资产归属，不是合成语义；重排/迁移时不能改变 TTS 签名。
    "segment_key",
    "regenerated",
    "regenerated_at",
    "regenerate_reason",
    "regenerated_preview_type",
}


class _SegmentView:
    def __init__(self, value: Dict[str, Any]):
        self._value = value

    def __getattr__(self, name: str) -> Any:
        return self._value.get(name)


def _segment_value(segment: Any, name: str) -> Any:
    if isinstance(segment, dict):
        return segment.get(name)
    return getattr(segment, name, None)


def _canonical_sha1(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def _without_derived_voice_params(segment: Dict[str, Any]) -> Dict[str, Any]:
    normalized = copy.deepcopy(segment)
    for field_name in CLIENT_FORBIDDEN_VOICE_IDENTITY_CONTROL_FIELDS:
        normalized.pop(field_name, None)
    voice_params = normalized.get("voice_params")
    if isinstance(voice_params, dict):
        voice_params = _strip_client_voice_identity_controls(voice_params)
        normalized["voice_params"] = {
            key: value
            for key, value in voice_params.items()
            if key not in DERIVED_VOICE_PARAM_FIELDS
        }
    elif voice_params is not None:
        normalized["voice_params"] = {}
    return normalized


def _strip_client_voice_identity_controls(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_client_voice_identity_controls(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _strip_client_voice_identity_controls(item)
        for key, item in value.items()
        if key not in CLIENT_FORBIDDEN_VOICE_IDENTITY_CONTROL_FIELDS
    }


def sanitize_segment_override(
    requested_segment: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Remove server-owned asset and compiled fields from a client override."""
    if requested_segment is None:
        return None
    sanitized = {
        key: copy.deepcopy(value)
        for key, value in requested_segment.items()
        if key not in SERVER_MANAGED_SEGMENT_ASSET_FIELDS
    }
    return _without_derived_voice_params(sanitized)


def resolve_server_owned_mimo_design_params(
    *,
    tts_model: str,
    voice_id: str = "",
    mimo_voice_asset_id: str = "",
    owner_user_id: Optional[int] = None,
    merge_asset_params: Optional[
        Callable[..., Dict[str, Any]]
    ] = None,
) -> Dict[str, Any]:
    """Resolve an immutable MiMo design recipe from the owner's asset store."""

    normalized_model = normalize_audiobook_tts_model(tts_model, default=str(tts_model or ""))
    selected_voice_id = str(voice_id or "").strip()
    asset_reference = (
        selected_voice_id
        if selected_voice_id.startswith("mimo_design:")
        else str(mimo_voice_asset_id or selected_voice_id).strip()
    )
    is_saved_design = asset_reference.startswith("mimo_design:") or bool(
        str(mimo_voice_asset_id or "").strip()
        and normalized_model == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    )
    if not is_saved_design:
        return {}
    if normalized_model != MIMO_V25_TTS_VOICE_DESIGN_MODEL:
        raise ValueError("MiMo 设计音色与片段绑定的 TTS 模型不一致")
    if owner_user_id is None:
        raise ValueError("固定 MiMo 设计音色缺少所有者上下文，无法安全加载音色配方")

    if not asset_reference.startswith("mimo_design:"):
        asset_reference = f"mimo_design:{asset_reference}"
    asset_id = asset_reference.removeprefix("mimo_design:").strip()
    resolver = merge_asset_params or mimo_voice_assets.merge_mimo_voice_asset_tts_params
    resolved = resolver(
        {
            "speaker": str(voice_id or asset_reference).strip(),
            "voice_id": str(voice_id or asset_reference).strip(),
            "mimo_voice_asset_id": asset_id,
        },
        owner_user_id=owner_user_id,
    )
    prompt = str(resolved.get("voice_design_prompt") or "").strip()
    if not prompt:
        raise ValueError("固定 MiMo 设计音色缺少服务端音色配方")
    return {
        "mimo_voice_asset_id": str(
            resolved.get("mimo_voice_asset_id") or asset_id
        ).strip(),
        "voice_design_prompt": prompt,
    }


def compute_segment_semantic_fingerprint(segment: Dict[str, Any]) -> str:
    """Hash durable synthesis intent, excluding assets and compiled snapshots."""
    normalized = _without_derived_voice_params(segment if isinstance(segment, dict) else {})
    payload = {
        key: value
        for key, value in normalized.items()
        if key not in _FINGERPRINT_EXCLUDED_FIELDS
    }
    return _canonical_sha1(payload)


def compute_compiled_segment_fingerprint(segment: Dict[str, Any]) -> str:
    """Hash the exact compiled segment stored in a candidate contract."""
    payload = {
        key: copy.deepcopy(value)
        for key, value in (segment or {}).items()
        if key not in _FINGERPRINT_EXCLUDED_FIELDS
    }
    return _canonical_sha1(payload)


def compile_segment_prompt_contract(
    *,
    segment: Any,
    voice_params: Dict[str, Any],
    tts_model: str,
    voice_id: str,
    emotion: str,
) -> Dict[str, Any]:
    """Rebuild provider-facing prompt fields from the current segment intent."""
    compiled_params = stabilize_instruct_model_speed(
        stabilize_fixed_voice_pitch(
            {
                key: value
                for key, value in dict(voice_params or {}).items()
                if key not in PROVIDER_PROMPT_DERIVED_FIELDS
            }
        ),
        tts_model,
    )
    voice_design_creation = is_voice_design_creation_request(tts_model, compiled_params)
    if not voice_design_creation:
        compiled_params, _ = sanitize_fixed_voice_prompt_params(compiled_params)

    plan_segment = _SegmentView(
        {
            "type": compiled_params.get("segment_type") or _segment_value(segment, "type"),
            "speaker": compiled_params.get("segment_speaker") or _segment_value(segment, "speaker"),
            "text": _segment_value(segment, "text"),
            "emotion": compiled_params.get("emotion") or _segment_value(segment, "emotion"),
            "performance_notes": compiled_params.get("performance_notes") or "",
            "instruct_emotion": compiled_params.get("instruct_emotion") or "",
            "instruct_scene": compiled_params.get("instruct_scene") or "",
            "instruct_role": compiled_params.get("instruct_role") or "",
            "instruct_identity": compiled_params.get("instruct_identity") or "",
        }
    )

    delivery_plan = build_delivery_plan(
        segment=plan_segment,
        voice_params=compiled_params,
        model=tts_model,
        emotion=emotion,
    )
    compiled_params["delivery_plan"] = delivery_plan
    if not voice_design_creation:
        compiled_params, _ = sanitize_fixed_voice_prompt_params(compiled_params)
        delivery_plan = dict(compiled_params.get("delivery_plan") or {})
    style_control = build_model_style_control(tts_model, compiled_params, emotion)
    compiled_params["provider_prompt_snapshot"] = build_provider_prompt_snapshot(
        model=tts_model,
        voice_id=voice_id,
        style_control=style_control,
        delivery_plan=delivery_plan,
    )
    return compiled_params


def compile_segment_synthesis_input(
    segment: Dict[str, Any],
    *,
    tts_model: str,
    voice_id: str,
    emotion: str,
    preview_type: str,
    server_owned_voice_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile a segment and the exact synthesis fingerprint used by a candidate."""
    compiled_segment = _without_derived_voice_params(segment if isinstance(segment, dict) else {})
    voice_params = compiled_segment.get("voice_params")
    if not isinstance(voice_params, dict):
        voice_params = {}
    else:
        voice_params = dict(voice_params)

    trusted_params = server_owned_voice_params if isinstance(server_owned_voice_params, Mapping) else {}
    for field_name in SERVER_OWNED_VOICE_ASSET_PARAM_FIELDS:
        if field_name in trusted_params and trusted_params[field_name] not in (None, ""):
            voice_params[field_name] = copy.deepcopy(trusted_params[field_name])

    voice_params["speaker"] = str(voice_id or "")
    voice_params["tts_model"] = str(tts_model or "")
    voice_params["resolved_tts_model"] = str(tts_model or "")
    voice_params["emotion"] = str(emotion or "neutral")
    voice_params["segment_speaker"] = str(compiled_segment.get("speaker") or "")
    voice_params["segment_type"] = str(compiled_segment.get("type") or "")
    voice_params["instruct_emotion"] = str(
        compiled_segment.get("instruct_emotion") or emotion or "neutral"
    )
    voice_params["instruct_scene"] = str(compiled_segment.get("instruct_scene") or "")
    voice_params["instruct_role"] = str(compiled_segment.get("instruct_role") or "")
    voice_params["instruct_identity"] = str(compiled_segment.get("instruct_identity") or "")

    performance_notes = str(compiled_segment.get("performance_notes") or "").strip()
    if performance_notes:
        voice_params["performance_notes"] = performance_notes
    use_instruct_mode = bool(
        voice_params["instruct_emotion"]
        or voice_params["instruct_scene"]
        or voice_params["instruct_role"]
        or voice_params["instruct_identity"]
        or performance_notes
    )
    voice_params["use_instruct_mode"] = use_instruct_mode

    segment_view = _SegmentView(compiled_segment)
    voice_params = compile_segment_prompt_contract(
        segment=segment_view,
        voice_params=voice_params,
        tts_model=tts_model,
        voice_id=voice_id,
        emotion=emotion,
    )
    compiled_segment["voice_params"] = voice_params

    text = str(compiled_segment.get("text") or "").strip()
    synthesis_payload = {
        "version": CONTRACT_VERSION,
        "revision": CANDIDATE_CONTRACT_REVISION,
        "preview_type": str(preview_type or "voice"),
        "tts_model": str(tts_model or ""),
        "text": text,
        "emotion": str(emotion or "neutral"),
        "voice_params": voice_params,
    }
    if str(preview_type or "voice") != "voice":
        synthesis_payload["segment"] = compiled_segment

    result = {
        "segment": compiled_segment,
        "text": text,
        "voice_params": voice_params,
        "emotion": str(emotion or "neutral"),
        "tts_model": str(tts_model or ""),
        "candidate_contract_revision": CANDIDATE_CONTRACT_REVISION,
        "effective_segment_fingerprint": compute_compiled_segment_fingerprint(
            compiled_segment
        ),
        "synthesis_fingerprint": _canonical_sha1(synthesis_payload),
    }
    trusted_prompt = str(voice_params.get("voice_design_prompt") or "").strip()
    trusted_asset_id = str(voice_params.get("mimo_voice_asset_id") or "").strip()
    if trusted_prompt and trusted_asset_id:
        result["voice_identity_binding"] = {
            "asset_type": "design",
            "mimo_voice_asset_id": trusted_asset_id,
            "voice_design_prompt_sha1": hashlib.sha1(
                trusted_prompt.encode("utf-8")
            ).hexdigest(),
        }
    return result


__all__ = [
    "CANDIDATE_CONTRACT_REVISION",
    "CLIENT_FORBIDDEN_VOICE_IDENTITY_CONTROL_FIELDS",
    "CONTRACT_VERSION",
    "DERIVED_VOICE_PARAM_FIELDS",
    "PROVIDER_PROMPT_DERIVED_FIELDS",
    "SERVER_OWNED_VOICE_ASSET_PARAM_FIELDS",
    "compile_segment_prompt_contract",
    "compile_segment_synthesis_input",
    "compute_compiled_segment_fingerprint",
    "compute_segment_semantic_fingerprint",
    "resolve_server_owned_mimo_design_params",
    "sanitize_segment_override",
]
