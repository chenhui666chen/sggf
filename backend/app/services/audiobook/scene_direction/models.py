"""Seed 场景导演数据合同（指导文档 §5）。

统一模型语义：

- 所有具有明确词义的内容（前景台词、背景短句、重叠插话、群体中可辨识台词）
  由 ``SeedSpeechDirection`` 表达；背景插话只是 layer/anchor 维度，不是新台词类型。
- ``SeedVocalizationDirection`` 只表示非语言人声，不携带 text 字段，不进入 transcript。
- 导演输出不携带可被信任的台词副本：Prompt 编译时按 source_segment_index
  直接读取源片段的说话人和台词。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 合法枚举值（解析器与验证器共用）。
SPEECH_LAYERS = ("foreground", "background")
SPEECH_ANCHORS = ("sequence", "before", "during", "after", "overlap")
VERIFICATION_POLICIES = ("hard", "soft", "semantic_only")
VOCALIZATION_ANCHORS = ("before", "during", "after", "overlap")
VOCALIZATION_PROVENANCES = ("explicit", "inferred_performance")
EVIDENCE_SOURCES = ("segment", "reviewed_analysis")
EVIDENCE_FIELDS = ("text", "performance_notes", "instruct_scene")
SOUND_KINDS = ("sfx", "ambient", "music", "transition")
SOUND_ANCHORS = ("before", "during", "after", "throughout", "until_text", "overlap")
SOUND_LAYERS = ("foreground", "background")
TIMELINE_MODES = ("natural", "bounded", "strict")


@dataclass(frozen=True)
class SeedSceneContext:
    time: str = ""
    location: str = ""
    acoustic_space: str = ""
    ambient_state: str = ""
    emotional_arc: str = ""
    story_beat: str = ""
    carry_in: tuple[str, ...] = ()
    carry_out: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeedSpeechDirection:
    source_segment_index: int
    speaker: str
    layer: str = "foreground"
    anchor: str = "sequence"
    relative_to_segment_index: int | None = None
    performance: str = ""
    acoustic: str = ""
    verification_policy: str = "hard"
    start_s: float | None = None
    end_s: float | None = None


@dataclass(frozen=True)
class SegmentEvidenceRef:
    segment_index: int
    field: str
    excerpt: str


@dataclass(frozen=True)
class ReviewedAnalysisEvidenceRef:
    artifact_id: str
    artifact_version: str
    artifact_hash: str
    finding_id: str
    segment_indices: tuple[int, ...]
    excerpt: str
    kind: str = field(default="reviewed_analysis", init=False)


@dataclass(frozen=True)
class SeedVocalizationDirection:
    speaker: str
    description: str
    anchor: str
    relative_to_segment_index: int
    evidence: SegmentEvidenceRef | ReviewedAnalysisEvidenceRef
    layer: str = "background"
    performance: str = ""
    acoustic: str = ""
    provenance: str = "explicit"


@dataclass(frozen=True)
class SeedSoundDirection:
    kind: str
    description: str
    anchor: str
    relative_to_segment_index: int | None = None
    related_text: str = ""
    duration_s: float | None = None
    delay_s: float = 0.0
    layer: str = "background"
    sequence_group: str = ""


@dataclass(frozen=True)
class SeedSceneDirection:
    scene_key: str
    source_segment_indices: tuple[int, ...]
    context: SeedSceneContext
    speech: tuple[SeedSpeechDirection, ...]
    vocalizations: tuple[SeedVocalizationDirection, ...]
    sounds: tuple[SeedSoundDirection, ...]
    timeline_mode: str = "natural"
    target_duration_s: float | None = None


__all__ = [
    "EVIDENCE_FIELDS",
    "EVIDENCE_SOURCES",
    "ReviewedAnalysisEvidenceRef",
    "SOUND_ANCHORS",
    "SOUND_KINDS",
    "SOUND_LAYERS",
    "SPEECH_ANCHORS",
    "SPEECH_LAYERS",
    "SegmentEvidenceRef",
    "SeedSceneContext",
    "SeedSceneDirection",
    "SeedSoundDirection",
    "SeedSpeechDirection",
    "SeedVocalizationDirection",
    "TIMELINE_MODES",
    "VERIFICATION_POLICIES",
    "VOCALIZATION_ANCHORS",
    "VOCALIZATION_PROVENANCES",
]
