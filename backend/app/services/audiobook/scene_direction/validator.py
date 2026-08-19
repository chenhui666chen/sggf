"""Seed 场景导演计划验证器（指导文档 §5.2/§5.3/§5.5/§13.1）。

对解析后的 ``SeedSceneDirection[]`` 执行事实与覆盖校验：

- 覆盖不变量：每个有可辨识文本的 ScriptSegment 必须且只被一个 speech 消费，
  不遗漏、不重复、不重排，场景区间连续；
- 台词事实：speaker 必须等于源片段审定说话人；台词副本不在合同中（模型无
  text 字段），编译时按 source_segment_index 读取源片段；
- 锚定约束：background/overlap 必须显式引用相对片段；绝对时间只在
  bounded/strict timeline 模式允许；
- 证据校验：excerpt 必须为源字段子串；speaker 与证据片段兼容；审定分析证据
  必须覆盖锚定片段；推导型 vocalization 受 policy 闸门控制（首期默认关闭）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Sequence, Tuple

from .models import (
    ReviewedAnalysisEvidenceRef,
    SegmentEvidenceRef,
    SeedSceneDirection,
)


@dataclass(frozen=True)
class DirectionValidationError:
    code: str
    scene_key: str
    message: str = ""


@dataclass(frozen=True)
class DirectionValidationResult:
    errors: Tuple[DirectionValidationError, ...] = ()
    warnings: Tuple[DirectionValidationError, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_seed_scene_directions(
    directions: Sequence[SeedSceneDirection],
    segments: Sequence[Any],
    *,
    policy: Any = None,
) -> DirectionValidationResult:
    """验证导演计划对审定片段的事实一致性；返回稳定错误码集合。"""
    errors: List[DirectionValidationError] = []
    text_indices = tuple(
        index
        for index, segment in enumerate(segments)
        if str(getattr(segment, "text", "") or "").strip()
    )
    _check_coverage(directions, text_indices, errors)
    for direction in directions:
        scene_index_set = set(direction.source_segment_indices)
        if direction.source_segment_indices != tuple(
            range(
                direction.source_segment_indices[0],
                direction.source_segment_indices[0] + len(direction.source_segment_indices),
            )
        ):
            errors.append(
                DirectionValidationError(
                    "scene_indices_not_contiguous",
                    direction.scene_key,
                    "source_segment_indices must be a contiguous range",
                )
            )
        _check_speech(direction, segments, scene_index_set, errors)
        _check_vocalizations(direction, segments, scene_index_set, policy, errors)
        _check_sounds(direction, scene_index_set, errors)
    return DirectionValidationResult(errors=tuple(errors))


def _check_coverage(
    directions: Sequence[SeedSceneDirection],
    text_indices: Tuple[int, ...],
    errors: List[DirectionValidationError],
) -> None:
    consumed: List[int] = []
    for direction in directions:
        consumed.extend(
            speech.source_segment_index
            for speech in direction.speech
        )
    seen = set()
    for index in consumed:
        if index in seen:
            errors.append(
                DirectionValidationError("coverage_overlap", "", f"segment {index} consumed twice")
            )
        seen.add(index)
    for index in text_indices:
        if index not in seen:
            errors.append(
                DirectionValidationError(
                    f"coverage_missing:{index}", "", f"segment {index} not consumed"
                )
            )
    ordered = [index for index in consumed if index in set(text_indices)]
    if ordered != sorted(ordered):
        errors.append(
            DirectionValidationError("coverage_order", "", "dialogue order must follow segment order")
        )


def _check_speech(
    direction: SeedSceneDirection,
    segments: Sequence[Any],
    scene_index_set: set,
    errors: List[DirectionValidationError],
) -> None:
    for speech in direction.speech:
        index = speech.source_segment_index
        if index not in scene_index_set:
            errors.append(
                DirectionValidationError(
                    "speech_segment_outside_scene",
                    direction.scene_key,
                    f"segment {index} not in scene range",
                )
            )
            continue
        if 0 <= index < len(segments):
            reviewed_speaker = str(getattr(segments[index], "speaker", "") or "").strip()
            if reviewed_speaker and speech.speaker != reviewed_speaker:
                errors.append(
                    DirectionValidationError(
                        "speaker_mismatch",
                        direction.scene_key,
                        f"segment {index}: director speaker {speech.speaker!r} != reviewed {reviewed_speaker!r}",
                    )
                )
        if (speech.layer == "background" or speech.anchor in ("during", "overlap")) and (
            speech.relative_to_segment_index is None
        ):
            errors.append(
                DirectionValidationError(
                    "missing_relative_reference",
                    direction.scene_key,
                    f"segment {index}: background/overlap speech must reference a relative segment",
                )
            )
        if (speech.start_s is not None or speech.end_s is not None) and (
            direction.timeline_mode not in ("bounded", "strict")
        ):
            errors.append(
                DirectionValidationError(
                    "absolute_time_requires_timeline_mode",
                    direction.scene_key,
                    f"segment {index}: absolute time only allowed in bounded/strict timeline",
                )
            )


def _check_vocalizations(
    direction: SeedSceneDirection,
    segments: Sequence[Any],
    scene_index_set: set,
    policy: Any,
    errors: List[DirectionValidationError],
) -> None:
    for vocalization in direction.vocalizations:
        evidence = vocalization.evidence
        if isinstance(evidence, SegmentEvidenceRef):
            _check_segment_evidence(direction, vocalization, evidence, segments, errors)
        elif isinstance(evidence, ReviewedAnalysisEvidenceRef):
            if vocalization.relative_to_segment_index not in evidence.segment_indices:
                errors.append(
                    DirectionValidationError(
                        "reviewed_evidence_segment_not_covered",
                        direction.scene_key,
                        "reviewed analysis evidence must cover the anchored segment",
                    )
                )
        if vocalization.provenance == "inferred_performance":
            allowed = bool(getattr(policy, "allow_inferred_vocalizations", False))
            if not allowed:
                errors.append(
                    DirectionValidationError(
                        "inferred_vocalization_not_allowed",
                        direction.scene_key,
                        "inferred vocalizations disabled by policy",
                    )
                )
            else:
                allowed_types = tuple(getattr(policy, "allowed_inferred_vocalization_types", ()) or ())
                if not any(value in vocalization.description for value in allowed_types):
                    errors.append(
                        DirectionValidationError(
                            "inferred_vocalization_type_not_allowed",
                            direction.scene_key,
                            f"description {vocalization.description!r} not in allowed inferred types",
                        )
                    )


def _check_segment_evidence(
    direction: SeedSceneDirection,
    vocalization: Any,
    evidence: SegmentEvidenceRef,
    segments: Sequence[Any],
    errors: List[DirectionValidationError],
) -> None:
    index = evidence.segment_index
    if not (0 <= index < len(segments)):
        errors.append(
            DirectionValidationError(
                "evidence_segment_out_of_range",
                direction.scene_key,
                f"evidence segment {index} does not exist",
            )
        )
        return
    segment = segments[index]
    source_value = str(getattr(segment, evidence.field, "") or "")
    if evidence.excerpt not in source_value:
        errors.append(
            DirectionValidationError(
                "evidence_excerpt_not_substring",
                direction.scene_key,
                f"excerpt {evidence.excerpt!r} is not a substring of segment {index} field {evidence.field}",
            )
        )
    evidence_speaker = str(getattr(segment, "speaker", "") or "").strip()
    if evidence_speaker and vocalization.speaker != evidence_speaker:
        errors.append(
            DirectionValidationError(
                "evidence_segment_speaker_mismatch",
                direction.scene_key,
                f"vocalization speaker {vocalization.speaker!r} incompatible with evidence segment speaker {evidence_speaker!r}",
            )
        )


def _check_sounds(
    direction: SeedSceneDirection,
    scene_index_set: set,
    errors: List[DirectionValidationError],
) -> None:
    for sound in direction.sounds:
        if sound.relative_to_segment_index is not None and (
            sound.relative_to_segment_index not in scene_index_set
        ):
            errors.append(
                DirectionValidationError(
                    "sound_segment_outside_scene",
                    direction.scene_key,
                    f"sound references segment {sound.relative_to_segment_index} outside scene range",
                )
            )


__all__ = [
    "DirectionValidationError",
    "DirectionValidationResult",
    "validate_seed_scene_directions",
]
