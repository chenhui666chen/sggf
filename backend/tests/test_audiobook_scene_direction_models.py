"""阶段 3 Seed 场景导演合同：§5 数据模型与严格解析器测试。

覆盖指导文档 §5/§13.1：

- SeedSceneDirection 严格解析和非法字段拒绝；
- 解析器不做猜测性文本修补（只允许确定性的 markdown 围栏剥离）；
- 证据引用为必填判别联合（SegmentEvidenceRef | ReviewedAnalysisEvidenceRef）；
- 台词方向不携带可信台词副本（模型层无 text 字段）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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
from app.services.audiobook.scene_direction.parser import (  # noqa: E402
    DirectionParseError,
    parse_seed_scene_directions,
)


def _minimal_scene_payload(**overrides) -> dict:
    payload = {
        "scene_key": "scene_0001",
        "source_segment_indices": [0, 1],
        "context": {
            "time": "深夜",
            "location": "废弃车站",
            "acoustic_space": "空旷大厅，明显混响",
            "ambient_state": "远处风声",
            "emotional_arc": "从警惕到惊慌",
            "story_beat": "主角发现异常",
            "carry_in": [],
            "carry_out": ["远处风声"],
        },
        "speech": [
            {
                "source_segment_index": 0,
                "speaker": "林川",
                "layer": "foreground",
                "anchor": "sequence",
                "verification_policy": "hard",
            },
            {
                "source_segment_index": 1,
                "speaker": "林川",
                "layer": "foreground",
                "anchor": "sequence",
                "verification_policy": "hard",
            },
        ],
        "vocalizations": [
            {
                "speaker": "林川",
                "description": "倒吸一口气",
                "anchor": "before",
                "relative_to_segment_index": 1,
                "evidence": {
                    "source": "segment",
                    "segment_index": 0,
                    "field": "performance_notes",
                    "excerpt": "倒吸一口气",
                },
            }
        ],
        "sounds": [
            {
                "kind": "sfx",
                "description": "铁门缓慢推开，金属摩擦",
                "anchor": "before",
                "relative_to_segment_index": 0,
            }
        ],
        "timeline_mode": "natural",
        "target_duration_s": None,
    }
    payload.update(overrides)
    return payload


def _directions_payload(**overrides) -> dict:
    return {"scenes": [_minimal_scene_payload(**overrides)]}


class TestStrictParsing:
    def test_parses_complete_payload_into_frozen_models(self):
        raw = json.dumps(_directions_payload(), ensure_ascii=False)
        directions = parse_seed_scene_directions(raw)
        assert len(directions) == 1
        direction = directions[0]
        assert isinstance(direction, SeedSceneDirection)
        assert direction.scene_key == "scene_0001"
        assert direction.source_segment_indices == (0, 1)
        assert isinstance(direction.context, SeedSceneContext)
        assert direction.context.acoustic_space == "空旷大厅，明显混响"
        assert direction.context.carry_out == ("远处风声",)
        speech = direction.speech
        assert speech[0].speaker == "林川"
        assert speech[0].verification_policy == "hard"
        vocalization = direction.vocalizations[0]
        assert isinstance(vocalization.evidence, SegmentEvidenceRef)
        assert vocalization.evidence.field == "performance_notes"
        assert vocalization.provenance == "explicit"
        sound = direction.sounds[0]
        assert sound.kind == "sfx"
        assert sound.layer == "background"

    def test_models_are_frozen_and_speech_carries_no_text(self):
        directions = parse_seed_scene_directions(
            json.dumps(_directions_payload(), ensure_ascii=False)
        )
        direction = directions[0]
        with pytest.raises(Exception):
            direction.scene_key = "mutated"  # type: ignore[misc]
        # §5.2：导演输出不携带可被信任的台词副本。
        assert not hasattr(direction.speech[0], "text")
        assert not hasattr(direction.speech[0], "exact_text")

    def test_strips_markdown_fence_deterministically(self):
        raw = "```json\n" + json.dumps(_directions_payload(), ensure_ascii=False) + "\n```"
        directions = parse_seed_scene_directions(raw)
        assert directions[0].scene_key == "scene_0001"

    def test_rejects_invalid_json_without_guessing_repair(self):
        broken = '{"scenes": ['  # 截断 JSON，禁止猜测性修补
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(broken)
        assert excinfo.value.code == "invalid_json"

    def test_rejects_non_mapping_root(self):
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions("[1, 2]")
        assert excinfo.value.code == "invalid_root"


class TestIllegalFieldRejection:
    def test_rejects_unknown_top_level_field(self):
        payload = _directions_payload(volume_levels=[0.8])  # 分轨参数不得进入合同
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("unknown_field:")

    def test_rejects_invalid_speech_layer(self):
        payload = _directions_payload()
        payload["scenes"][0]["speech"][0]["layer"] = "whisper_track"
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("invalid_value:layer")

    def test_rejects_invalid_sound_kind(self):
        payload = _directions_payload()
        payload["scenes"][0]["sounds"][0]["kind"] = "stem"
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("invalid_value:kind")

    def test_rejects_missing_required_scene_field(self):
        payload = _directions_payload()
        del payload["scenes"][0]["source_segment_indices"]
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("missing_field:source_segment_indices")

    def test_rejects_empty_scene_list(self):
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps({"scenes": []}, ensure_ascii=False))
        assert excinfo.value.code == "empty_directions"


class TestEvidenceUnion:
    def test_rejects_vocalization_without_evidence(self):
        payload = _directions_payload()
        del payload["scenes"][0]["vocalizations"][0]["evidence"]
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("missing_field:evidence")

    def test_rejects_unknown_evidence_source(self):
        payload = _directions_payload()
        payload["scenes"][0]["vocalizations"][0]["evidence"] = {
            "source": "llm_self_report",
            "excerpt": "合理",
        }
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("invalid_value:evidence.source")

    def test_parses_reviewed_analysis_evidence(self):
        payload = _directions_payload()
        payload["scenes"][0]["vocalizations"][0]["evidence"] = {
            "source": "reviewed_analysis",
            "artifact_id": "analysis-1",
            "artifact_version": "1.0.0",
            "artifact_hash": "abc123",
            "finding_id": "finding-7",
            "segment_indices": [0],
            "excerpt": "她笑了一声",
        }
        directions = parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        evidence = directions[0].vocalizations[0].evidence
        assert isinstance(evidence, ReviewedAnalysisEvidenceRef)
        assert evidence.finding_id == "finding-7"
        assert evidence.segment_indices == (0,)

    def test_rejects_speech_text_field_in_contract(self):
        # §5.2：台词副本不属于导演输出合同，出现即拒绝（防止 LLM 回显被信任）。
        payload = _directions_payload()
        payload["scenes"][0]["speech"][0]["text"] = "这里有人吗？"
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("unknown_field:text")

    def test_rejects_invalid_vocalization_provenance(self):
        payload = _directions_payload()
        payload["scenes"][0]["vocalizations"][0]["provenance"] = "imagined"
        with pytest.raises(DirectionParseError) as excinfo:
            parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
        assert excinfo.value.code.startswith("invalid_value:provenance")
