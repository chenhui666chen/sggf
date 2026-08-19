"""阶段 3 Seed 场景导演合同：验证器测试（指导文档 §5.2/§5.3/§5.5/§13.1）。

覆盖：

- segment 引用完整、连续、有序（覆盖不变量：不遗漏、不重复、不重排）；
- speaker 必须等于源片段审定说话人（台词事实不被改写由模型无 text 字段保证）；
- background/overlap 必须显式引用相对片段；绝对时间只在 timeline 模式允许；
- 证据校验：excerpt 必须为源字段子串，speaker 与证据片段兼容，
  审定分析证据必须覆盖锚定片段；
- 推导型 vocalization 受 policy 闸门控制（首期默认关闭）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_direction.models import (  # noqa: E402
    ReviewedAnalysisEvidenceRef,
    SegmentEvidenceRef,
    SeedSceneContext,
    SeedSceneDirection,
    SeedSoundDirection,
    SeedSpeechDirection,
    SeedVocalizationDirection,
)
from app.services.audiobook.scene_direction.validator import (  # noqa: E402
    validate_seed_scene_directions,
)


def _segment(index: int, speaker: str, text: str, **extra) -> SimpleNamespace:
    base = {
        "type": "dialogue",
        "text": text,
        "speaker": speaker,
        "performance_notes": "",
        "instruct_scene": "",
    }
    base.update(extra)
    return SimpleNamespace(**base)


def _segments() -> list:
    return [
        _segment(0, "林川", "这里有人吗？", performance_notes="她笑了一声"),
        _segment(1, "苏眠", "别出声。"),
        _segment(2, "林川", "门是开着的。"),
    ]


def _speech(index: int, speaker: str, **extra) -> SeedSpeechDirection:
    return SeedSpeechDirection(source_segment_index=index, speaker=speaker, **extra)


def _scene(indices, speech, **extra) -> SeedSceneDirection:
    return SeedSceneDirection(
        scene_key=extra.pop("scene_key", "scene_0001"),
        source_segment_indices=tuple(indices),
        context=SeedSceneContext(),
        speech=tuple(speech),
        vocalizations=tuple(extra.pop("vocalizations", ())),
        sounds=tuple(extra.pop("sounds", ())),
        **extra,
    )


def _codes(result) -> set:
    return {error.code for error in result.errors}


class TestCoverageInvariants:
    def test_complete_contiguous_ordered_coverage_passes(self):
        direction = _scene(
            (0, 1, 2),
            [_speech(0, "林川"), _speech(1, "苏眠"), _speech(2, "林川")],
        )
        result = validate_seed_scene_directions((direction,), _segments())
        assert result.ok
        assert result.errors == ()

    def test_missing_text_segment_rejected(self):
        direction = _scene((0, 2), [_speech(0, "林川"), _speech(2, "林川")])
        result = validate_seed_scene_directions((direction,), _segments())
        assert not result.ok
        assert "coverage_missing:1" in _codes(result)

    def test_duplicate_consumption_rejected(self):
        first = _scene((0, 1), [_speech(0, "林川"), _speech(1, "苏眠")])
        second = _scene(
            (1, 2),
            [_speech(1, "苏眠"), _speech(2, "林川")],
            scene_key="scene_0002",
        )
        result = validate_seed_scene_directions((first, second), _segments())
        assert not result.ok
        assert "coverage_overlap" in _codes(result)

    def test_reordered_dialogue_rejected(self):
        direction = _scene(
            (0, 1, 2),
            [_speech(1, "苏眠"), _speech(0, "林川"), _speech(2, "林川")],
        )
        result = validate_seed_scene_directions((direction,), _segments())
        assert not result.ok
        assert "coverage_order" in _codes(result)

    def test_scene_indices_must_be_contiguous(self):
        direction = _scene(
            (0, 2),
            [_speech(0, "林川"), _speech(2, "林川")],
        )
        result = validate_seed_scene_directions((direction,), _segments())
        assert "scene_indices_not_contiguous" in _codes(result)


class TestSpeechFacts:
    def test_speaker_mismatch_rejected(self):
        direction = _scene((0, 1), [_speech(0, "苏眠"), _speech(1, "苏眠")])
        result = validate_seed_scene_directions((direction,), _segments())
        assert "speaker_mismatch" in _codes(result)

    def test_background_layer_requires_relative_reference(self):
        direction = _scene(
            (0, 1),
            [
                _speech(0, "林川"),
                _speech(1, "苏眠", layer="background", anchor="during"),
            ],
        )
        result = validate_seed_scene_directions((direction,), _segments())
        assert "missing_relative_reference" in _codes(result)

    def test_overlap_anchor_with_relative_reference_passes(self):
        direction = _scene(
            (0, 1),
            [
                _speech(0, "林川"),
                _speech(
                    1,
                    "苏眠",
                    layer="background",
                    anchor="overlap",
                    relative_to_segment_index=0,
                    verification_policy="soft",
                ),
            ],
        )
        result = validate_seed_scene_directions((direction,), _segments()[:2])
        assert result.ok

    def test_absolute_time_rejected_in_natural_timeline(self):
        direction = _scene(
            (0,),
            [_speech(0, "林川", start_s=1.0, end_s=3.0)],
            timeline_mode="natural",
        )
        result = validate_seed_scene_directions((direction,), _segments())
        assert "absolute_time_requires_timeline_mode" in _codes(result)

    def test_absolute_time_allowed_in_bounded_timeline(self):
        direction = _scene(
            (0,),
            [_speech(0, "林川", start_s=1.0, end_s=3.0)],
            timeline_mode="bounded",
        )
        result = validate_seed_scene_directions((direction,), _segments()[:1])
        assert result.ok

    def test_speech_outside_scene_range_rejected(self):
        direction = _scene((0, 1), [_speech(0, "林川"), _speech(1, "苏眠"), _speech(2, "林川")])
        result = validate_seed_scene_directions((direction,), _segments())
        assert "speech_segment_outside_scene" in _codes(result)


class TestVocalizationEvidence:
    def _vocalization(self, evidence, **extra) -> SeedVocalizationDirection:
        return SeedVocalizationDirection(
            speaker=extra.pop("speaker", "林川"),
            description=extra.pop("description", "轻笑"),
            anchor=extra.pop("anchor", "before"),
            relative_to_segment_index=extra.pop("relative_to_segment_index", 0),
            evidence=evidence,
            **extra,
        )

    def _direction_with_vocalization(self, vocalization):
        return _scene(
            (0,),
            [_speech(0, "林川")],
            vocalizations=(vocalization,),
        )

    def test_segment_evidence_excerpt_must_be_substring(self):
        vocalization = self._vocalization(
            SegmentEvidenceRef(segment_index=0, field="performance_notes", excerpt="她大哭起来")
        )
        result = validate_seed_scene_directions((self._direction_with_vocalization(vocalization),), _segments())
        assert "evidence_excerpt_not_substring" in _codes(result)

    def test_valid_segment_evidence_passes(self):
        vocalization = self._vocalization(
            SegmentEvidenceRef(segment_index=0, field="performance_notes", excerpt="笑了一声")
        )
        result = validate_seed_scene_directions((self._direction_with_vocalization(vocalization),), _segments()[:1])
        assert result.ok

    def test_evidence_speaker_mismatch_rejected(self):
        vocalization = self._vocalization(
            SegmentEvidenceRef(segment_index=1, field="text", excerpt="别出声"),
            speaker="林川",
        )
        result = validate_seed_scene_directions((self._direction_with_vocalization(vocalization),), _segments())
        assert "evidence_segment_speaker_mismatch" in _codes(result)

    def test_reviewed_analysis_evidence_must_cover_anchor_segment(self):
        vocalization = self._vocalization(
            ReviewedAnalysisEvidenceRef(
                artifact_id="analysis-1",
                artifact_version="1.0.0",
                artifact_hash="abc",
                finding_id="finding-1",
                segment_indices=(2,),
                excerpt="笑",
            )
        )
        result = validate_seed_scene_directions((self._direction_with_vocalization(vocalization),), _segments())
        assert "reviewed_evidence_segment_not_covered" in _codes(result)

    def test_inferred_vocalization_rejected_by_default_policy(self):
        vocalization = self._vocalization(
            SegmentEvidenceRef(segment_index=0, field="text", excerpt="这里有人吗"),
            description="吸气",
            provenance="inferred_performance",
        )
        result = validate_seed_scene_directions((self._direction_with_vocalization(vocalization),), _segments())
        assert "inferred_vocalization_not_allowed" in _codes(result)

    def test_inferred_vocalization_allowed_when_policy_opens_type(self):
        policy = SimpleNamespace(
            allow_inferred_vocalizations=True,
            allowed_inferred_vocalization_types=("吸气", "呼气"),
        )
        vocalization = self._vocalization(
            SegmentEvidenceRef(segment_index=0, field="text", excerpt="这里有人吗"),
            description="吸气",
            provenance="inferred_performance",
        )
        result = validate_seed_scene_directions(
            (self._direction_with_vocalization(vocalization),),
            _segments()[:1],
            policy=policy,
        )
        assert result.ok

    def test_inferred_strong_performance_rejected_even_when_open(self):
        policy = SimpleNamespace(
            allow_inferred_vocalizations=True,
            allowed_inferred_vocalization_types=("吸气", "呼气"),
        )
        vocalization = self._vocalization(
            SegmentEvidenceRef(segment_index=0, field="text", excerpt="这里有人吗"),
            description="大笑",
            provenance="inferred_performance",
        )
        result = validate_seed_scene_directions(
            (self._direction_with_vocalization(vocalization),),
            _segments(),
            policy=policy,
        )
        assert "inferred_vocalization_type_not_allowed" in _codes(result)


class TestSoundAnchors:
    def test_sound_relative_reference_must_be_in_scene(self):
        direction = _scene(
            (0,),
            [_speech(0, "林川")],
            sounds=(
                SeedSoundDirection(
                    kind="sfx",
                    description="铁门摩擦",
                    anchor="before",
                    relative_to_segment_index=2,
                ),
            ),
        )
        result = validate_seed_scene_directions((direction,), _segments())
        assert "sound_segment_outside_scene" in _codes(result)
