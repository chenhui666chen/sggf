"""Seed 场景导演计划严格解析器（指导文档 §4.2）。

只解析严格 JSON：允许确定性的 markdown 围栏剥离，禁止任何猜测性文本修补。
未知字段一律拒绝（防止分轨参数、台词副本等越权字段混入合同）。
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Tuple

from .models import (
    EVIDENCE_FIELDS,
    ReviewedAnalysisEvidenceRef,
    SOUND_ANCHORS,
    SOUND_KINDS,
    SOUND_LAYERS,
    SPEECH_ANCHORS,
    SPEECH_LAYERS,
    SegmentEvidenceRef,
    SeedSceneContext,
    SeedSceneDirection,
    SeedSoundDirection,
    SeedSpeechDirection,
    SeedVocalizationDirection,
    TIMELINE_MODES,
    VERIFICATION_POLICIES,
    VOCALIZATION_ANCHORS,
    VOCALIZATION_PROVENANCES,
)


class DirectionParseError(ValueError):
    """导演计划解析失败；``code`` 为稳定错误码，供纠错 Prompt 与账本引用。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


_CONTEXT_FIELDS = {
    "time": str,
    "location": str,
    "acoustic_space": str,
    "ambient_state": str,
    "emotional_arc": str,
    "story_beat": str,
}
_CONTEXT_LIST_FIELDS = ("carry_in", "carry_out")

_SPEECH_REQUIRED = {"source_segment_index": int, "speaker": str}
_SPEECH_OPTIONAL_STR = {"performance": "", "acoustic": ""}
_SPEECH_ENUMS = {
    "layer": SPEECH_LAYERS,
    "anchor": SPEECH_ANCHORS,
    "verification_policy": VERIFICATION_POLICIES,
}

_VOCALIZATION_REQUIRED_STR = ("speaker", "description")
_SOUND_REQUIRED_STR = ("description",)


def parse_seed_scene_directions(raw_text: str) -> Tuple[SeedSceneDirection, ...]:
    """解析导演 LLM 输出为 ``SeedSceneDirection[]``；任何非法结构抛 DirectionParseError。"""
    payload = _load_json(raw_text)
    if not isinstance(payload, Mapping):
        raise DirectionParseError("invalid_root", "root must be a JSON object")
    _reject_unknown_fields(payload, {"scenes"}, path="root")
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise DirectionParseError("empty_directions", "scenes must be a non-empty list")
    return tuple(
        _parse_scene(scene, position=index) for index, scene in enumerate(scenes)
    )


def _load_json(raw_text: str) -> Any:
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        # 确定性围栏剥离：仅去掉首尾 ``` 行，不做其他修补。
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DirectionParseError("invalid_json", str(exc)) from exc


def _reject_unknown_fields(
    payload: Mapping[str, Any], allowed: set, *, path: str
) -> None:
    for key in payload:
        if key not in allowed:
            raise DirectionParseError(f"unknown_field:{key}", f"{path}.{key}")


def _require_fields(payload: Mapping[str, Any], names: Tuple[str, ...], *, path: str) -> None:
    for name in names:
        if name not in payload or payload[name] is None:
            raise DirectionParseError(f"missing_field:{name}", f"{path}.{name}")


def _parse_scene(payload: Any, *, position: int) -> SeedSceneDirection:
    path = f"scenes[{position}]"
    if not isinstance(payload, Mapping):
        raise DirectionParseError("invalid_root", f"{path} must be an object")
    _reject_unknown_fields(
        payload,
        {
            "scene_key",
            "source_segment_indices",
            "context",
            "speech",
            "vocalizations",
            "sounds",
            "timeline_mode",
            "target_duration_s",
        },
        path=path,
    )
    _require_fields(payload, ("scene_key", "source_segment_indices"), path=path)
    scene_key = _parse_str(payload["scene_key"], field_name="scene_key", path=path)
    indices = _parse_index_list(
        payload["source_segment_indices"], field_name="source_segment_indices", path=path
    )
    if not indices:
        raise DirectionParseError("missing_field:source_segment_indices", path)
    context = _parse_context(payload.get("context"), path=path)
    speech = tuple(
        _parse_speech(item, path=f"{path}.speech[{index}]")
        for index, item in enumerate(payload.get("speech") or ())
    )
    vocalizations = tuple(
        _parse_vocalization(item, path=f"{path}.vocalizations[{index}]")
        for index, item in enumerate(payload.get("vocalizations") or ())
    )
    sounds = tuple(
        _parse_sound(item, path=f"{path}.sounds[{index}]")
        for index, item in enumerate(payload.get("sounds") or ())
    )
    timeline_mode = _parse_enum(
        payload.get("timeline_mode", "natural"),
        TIMELINE_MODES,
        field_name="timeline_mode",
        path=path,
    )
    target_duration = _parse_optional_float(
        payload.get("target_duration_s"), field_name="target_duration_s", path=path
    )
    return SeedSceneDirection(
        scene_key=scene_key,
        source_segment_indices=indices,
        context=context,
        speech=speech,
        vocalizations=vocalizations,
        sounds=sounds,
        timeline_mode=timeline_mode,
        target_duration_s=target_duration,
    )


def _parse_context(payload: Any, *, path: str) -> SeedSceneContext:
    if payload is None:
        return SeedSceneContext()
    if not isinstance(payload, Mapping):
        raise DirectionParseError("invalid_root", f"{path}.context must be an object")
    allowed = set(_CONTEXT_FIELDS) | set(_CONTEXT_LIST_FIELDS)
    _reject_unknown_fields(payload, allowed, path=f"{path}.context")
    values = {}
    for name, expected in _CONTEXT_FIELDS.items():
        value = payload.get(name, "")
        if not isinstance(value, expected):
            raise DirectionParseError(f"invalid_value:{name}", f"{path}.context.{name}")
        values[name] = value
    for name in _CONTEXT_LIST_FIELDS:
        raw_items = payload.get(name) or ()
        if not isinstance(raw_items, (list, tuple)):
            raise DirectionParseError(f"invalid_value:{name}", f"{path}.context.{name}")
        items = []
        for item in raw_items:
            if not isinstance(item, str):
                raise DirectionParseError(f"invalid_value:{name}", f"{path}.context.{name}")
            items.append(item)
        values[name] = tuple(items)
    return SeedSceneContext(**values)


def _parse_speech(payload: Any, *, path: str) -> SeedSpeechDirection:
    if not isinstance(payload, Mapping):
        raise DirectionParseError("invalid_root", f"{path} must be an object")
    _reject_unknown_fields(
        payload,
        {
            "source_segment_index",
            "speaker",
            "layer",
            "anchor",
            "relative_to_segment_index",
            "performance",
            "acoustic",
            "verification_policy",
            "start_s",
            "end_s",
        },
        path=path,
    )
    _require_fields(payload, tuple(_SPEECH_REQUIRED), path=path)
    source_index = _parse_index(
        payload["source_segment_index"], field_name="source_segment_index", path=path
    )
    speaker = _parse_str(payload["speaker"], field_name="speaker", path=path)
    values = {}
    for name, allowed in _SPEECH_ENUMS.items():
        values[name] = _parse_enum(
            payload.get(name, allowed[0]), allowed, field_name=name, path=path
        )
    for name, default in _SPEECH_OPTIONAL_STR.items():
        value = payload.get(name, default)
        if not isinstance(value, str):
            raise DirectionParseError(f"invalid_value:{name}", f"{path}.{name}")
        values[name] = value
    relative = payload.get("relative_to_segment_index")
    relative_index = (
        None if relative is None else _parse_index(relative, field_name="relative_to_segment_index", path=path)
    )
    start_s = _parse_optional_float(payload.get("start_s"), field_name="start_s", path=path)
    end_s = _parse_optional_float(payload.get("end_s"), field_name="end_s", path=path)
    return SeedSpeechDirection(
        source_segment_index=source_index,
        speaker=speaker,
        relative_to_segment_index=relative_index,
        start_s=start_s,
        end_s=end_s,
        **values,
    )


def _parse_vocalization(payload: Any, *, path: str) -> SeedVocalizationDirection:
    if not isinstance(payload, Mapping):
        raise DirectionParseError("invalid_root", f"{path} must be an object")
    _reject_unknown_fields(
        payload,
        {
            "speaker",
            "description",
            "anchor",
            "relative_to_segment_index",
            "evidence",
            "layer",
            "performance",
            "acoustic",
            "provenance",
        },
        path=path,
    )
    _require_fields(
        payload,
        ("speaker", "description", "anchor", "relative_to_segment_index", "evidence"),
        path=path,
    )
    speaker = _parse_str(payload["speaker"], field_name="speaker", path=path)
    description = _parse_str(payload["description"], field_name="description", path=path)
    anchor = _parse_enum(payload["anchor"], VOCALIZATION_ANCHORS, field_name="anchor", path=path)
    relative_index = _parse_index(
        payload["relative_to_segment_index"],
        field_name="relative_to_segment_index",
        path=path,
    )
    evidence = _parse_evidence(payload["evidence"], path=path)
    layer = _parse_enum(payload.get("layer", "background"), SOUND_LAYERS, field_name="layer", path=path)
    provenance = _parse_enum(
        payload.get("provenance", "explicit"),
        VOCALIZATION_PROVENANCES,
        field_name="provenance",
        path=path,
    )
    performance = payload.get("performance", "")
    acoustic = payload.get("acoustic", "")
    if not isinstance(performance, str) or not isinstance(acoustic, str):
        raise DirectionParseError("invalid_value:performance", path)
    return SeedVocalizationDirection(
        speaker=speaker,
        description=description,
        anchor=anchor,
        relative_to_segment_index=relative_index,
        evidence=evidence,
        layer=layer,
        performance=performance,
        acoustic=acoustic,
        provenance=provenance,
    )


def _parse_evidence(payload: Any, *, path: str) -> SegmentEvidenceRef | ReviewedAnalysisEvidenceRef:
    if not isinstance(payload, Mapping):
        raise DirectionParseError("invalid_value:evidence", f"{path}.evidence must be an object")
    source = payload.get("source")
    if source == "segment":
        _reject_unknown_fields(payload, {"source", "segment_index", "field", "excerpt"}, path=f"{path}.evidence")
        _require_fields(payload, ("segment_index", "field", "excerpt"), path=f"{path}.evidence")
        field_name = _parse_enum(
            payload["field"], EVIDENCE_FIELDS, field_name="evidence.field", path=path
        )
        return SegmentEvidenceRef(
            segment_index=_parse_index(
                payload["segment_index"], field_name="evidence.segment_index", path=path
            ),
            field=field_name,
            excerpt=_parse_str(payload["excerpt"], field_name="evidence.excerpt", path=path),
        )
    if source == "reviewed_analysis":
        _reject_unknown_fields(
            payload,
            {
                "source",
                "artifact_id",
                "artifact_version",
                "artifact_hash",
                "finding_id",
                "segment_indices",
                "excerpt",
            },
            path=f"{path}.evidence",
        )
        _require_fields(
            payload,
            (
                "artifact_id",
                "artifact_version",
                "artifact_hash",
                "finding_id",
                "segment_indices",
                "excerpt",
            ),
            path=f"{path}.evidence",
        )
        return ReviewedAnalysisEvidenceRef(
            artifact_id=_parse_str(payload["artifact_id"], field_name="evidence.artifact_id", path=path),
            artifact_version=_parse_str(
                payload["artifact_version"], field_name="evidence.artifact_version", path=path
            ),
            artifact_hash=_parse_str(
                payload["artifact_hash"], field_name="evidence.artifact_hash", path=path
            ),
            finding_id=_parse_str(payload["finding_id"], field_name="evidence.finding_id", path=path),
            segment_indices=_parse_index_list(
                payload["segment_indices"], field_name="evidence.segment_indices", path=path
            ),
            excerpt=_parse_str(payload["excerpt"], field_name="evidence.excerpt", path=path),
        )
    raise DirectionParseError(
        "invalid_value:evidence.source", f"{path}.evidence.source must be segment|reviewed_analysis"
    )


def _parse_sound(payload: Any, *, path: str) -> SeedSoundDirection:
    if not isinstance(payload, Mapping):
        raise DirectionParseError("invalid_root", f"{path} must be an object")
    _reject_unknown_fields(
        payload,
        {
            "kind",
            "description",
            "anchor",
            "relative_to_segment_index",
            "related_text",
            "duration_s",
            "delay_s",
            "layer",
            "sequence_group",
        },
        path=path,
    )
    _require_fields(payload, ("kind", "description", "anchor"), path=path)
    kind = _parse_enum(payload["kind"], SOUND_KINDS, field_name="kind", path=path)
    description = _parse_str(payload["description"], field_name="description", path=path)
    anchor = _parse_enum(payload["anchor"], SOUND_ANCHORS, field_name="anchor", path=path)
    relative = payload.get("relative_to_segment_index")
    relative_index = (
        None if relative is None else _parse_index(relative, field_name="relative_to_segment_index", path=path)
    )
    related_text = payload.get("related_text", "")
    sequence_group = payload.get("sequence_group", "")
    if not isinstance(related_text, str) or not isinstance(sequence_group, str):
        raise DirectionParseError("invalid_value:related_text", path)
    duration_s = _parse_optional_float(payload.get("duration_s"), field_name="duration_s", path=path)
    delay_s = payload.get("delay_s", 0.0)
    if not isinstance(delay_s, (int, float)) or isinstance(delay_s, bool):
        raise DirectionParseError("invalid_value:delay_s", path)
    layer = _parse_enum(payload.get("layer", "background"), SOUND_LAYERS, field_name="layer", path=path)
    return SeedSoundDirection(
        kind=kind,
        description=description,
        anchor=anchor,
        relative_to_segment_index=relative_index,
        related_text=related_text,
        duration_s=duration_s,
        delay_s=float(delay_s),
        layer=layer,
        sequence_group=sequence_group,
    )


def _parse_str(value: Any, *, field_name: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DirectionParseError(f"invalid_value:{field_name}", f"{path}.{field_name} must be a non-empty string")
    return value.strip()


def _parse_enum(value: Any, allowed: Tuple[str, ...], *, field_name: str, path: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise DirectionParseError(
            f"invalid_value:{field_name}",
            f"{path}.{field_name} must be one of {'|'.join(allowed)}",
        )
    return value


def _parse_index(value: Any, *, field_name: str, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DirectionParseError(f"invalid_value:{field_name}", f"{path}.{field_name} must be a non-negative int")
    return value


def _parse_index_list(value: Any, *, field_name: str, path: str) -> Tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise DirectionParseError(f"invalid_value:{field_name}", f"{path}.{field_name} must be a list")
    return tuple(
        _parse_index(item, field_name=f"{field_name}[{index}]", path=path)
        for index, item in enumerate(value)
    )


def _parse_optional_float(value: Any, *, field_name: str, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DirectionParseError(f"invalid_value:{field_name}", f"{path}.{field_name} must be a number")
    return float(value)


__all__ = ["DirectionParseError", "parse_seed_scene_directions", "serialize_seed_scene_directions"]


def serialize_seed_scene_directions(
    directions: Tuple[SeedSceneDirection, ...],
) -> dict:
    """把导演计划序列化为与 LLM 输出同构的 JSON payload（供 checkpoint 持久化）。"""
    return {"scenes": [_serialize_scene(direction) for direction in directions]}


def _serialize_scene(direction: SeedSceneDirection) -> dict:
    return {
        "scene_key": direction.scene_key,
        "source_segment_indices": list(direction.source_segment_indices),
        "context": {
            "time": direction.context.time,
            "location": direction.context.location,
            "acoustic_space": direction.context.acoustic_space,
            "ambient_state": direction.context.ambient_state,
            "emotional_arc": direction.context.emotional_arc,
            "story_beat": direction.context.story_beat,
            "carry_in": list(direction.context.carry_in),
            "carry_out": list(direction.context.carry_out),
        },
        "speech": [_serialize_speech(speech) for speech in direction.speech],
        "vocalizations": [
            _serialize_vocalization(vocalization) for vocalization in direction.vocalizations
        ],
        "sounds": [_serialize_sound(sound) for sound in direction.sounds],
        "timeline_mode": direction.timeline_mode,
        "target_duration_s": direction.target_duration_s,
    }


def _serialize_speech(speech: SeedSpeechDirection) -> dict:
    return {
        "source_segment_index": speech.source_segment_index,
        "speaker": speech.speaker,
        "layer": speech.layer,
        "anchor": speech.anchor,
        "relative_to_segment_index": speech.relative_to_segment_index,
        "performance": speech.performance,
        "acoustic": speech.acoustic,
        "verification_policy": speech.verification_policy,
        "start_s": speech.start_s,
        "end_s": speech.end_s,
    }


def _serialize_vocalization(vocalization: SeedVocalizationDirection) -> dict:
    evidence = vocalization.evidence
    if isinstance(evidence, SegmentEvidenceRef):
        evidence_payload = {
            "source": "segment",
            "segment_index": evidence.segment_index,
            "field": evidence.field,
            "excerpt": evidence.excerpt,
        }
    else:
        evidence_payload = {
            "source": "reviewed_analysis",
            "artifact_id": evidence.artifact_id,
            "artifact_version": evidence.artifact_version,
            "artifact_hash": evidence.artifact_hash,
            "finding_id": evidence.finding_id,
            "segment_indices": list(evidence.segment_indices),
            "excerpt": evidence.excerpt,
        }
    return {
        "speaker": vocalization.speaker,
        "description": vocalization.description,
        "anchor": vocalization.anchor,
        "relative_to_segment_index": vocalization.relative_to_segment_index,
        "evidence": evidence_payload,
        "layer": vocalization.layer,
        "performance": vocalization.performance,
        "acoustic": vocalization.acoustic,
        "provenance": vocalization.provenance,
    }


def _serialize_sound(sound: SeedSoundDirection) -> dict:
    return {
        "kind": sound.kind,
        "description": sound.description,
        "anchor": sound.anchor,
        "relative_to_segment_index": sound.relative_to_segment_index,
        "related_text": sound.related_text,
        "duration_s": sound.duration_s,
        "delay_s": sound.delay_s,
        "layer": sound.layer,
        "sequence_group": sound.sequence_group,
    }
