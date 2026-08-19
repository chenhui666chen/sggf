"""阶段 5 Omni 期望合同规范化测试（指导文档 §12.2 OmniReviewCheckpointSignature）。

覆盖：

- omni_expectation_contract_hash 必须覆盖 §10.2 完整 Omni 输入合同：
  scene context、speech 与验证策略、vocalizations、声音事件及其时序、
  音乐/环境生命周期、声学处理、performance 期望、timeline 窗口、
  voice binding summary、carry state、场景目标时长；
- 缺任一部分即拒绝（不完整合同不得成为评审缓存键）；
- 规范化与字段顺序无关：只改 mapping 键顺序 hash 不变；
  有顺序语义的数组（台词顺序、事件时序）顺序变化必须改变 hash；
- voice_binding_summary_hash 与期望合同从同一规范化来源生成，
  避免双重字段语义不一致；
- 二进制内容拒绝进入规范化（canonical_hash 职责边界）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.expectation_contract import (  # noqa: E402
    EXPECTATION_REQUIRED_PARTS,
    build_voice_binding_summary,
    omni_expectation_contract_hash,
)


def _expectation(**overrides):
    payload = {
        "scene_context": {"scene_id": "scene-001", "location": "灵山山门前"},
        "speech": [
            {
                "text": "师兄，护住山门！",
                "speaker": "弟子",
                "validation": "hard",
                "layer": "foreground",
            },
            {
                "text": "结阵，莫乱！",
                "speaker": "师兄",
                "validation": "hard",
                "layer": "foreground",
            },
        ],
        "vocalizations": [
            {"speaker": "弟子", "term": "喘息", "anchor": "after"}
        ],
        "sound_events": [
            {"acoustic": "金属碰撞", "anchor": "during", "timing_order": 1},
            {"acoustic": "法术爆鸣", "anchor": "after", "timing_order": 2},
        ],
        "music_ambient": {
            "music": "低沉法号由远及近",
            "ambient": "远处风声持续",
            "lifecycle": "fade_out_at_end",
        },
        "acoustic_treatment": ["石壁明显混响"],
        "performance_expectations": ["对白始终清晰位于前景"],
        "timeline_windows": [],
        "voice_binding_summary": [
            {"speaker": "弟子", "slot_index": 1, "reference_content_hash": "h-1"},
            {"speaker": "师兄", "slot_index": 2, "reference_content_hash": "h-2"},
        ],
        "carry_state": {"carry_in": None, "carry_out": "钟鸣尾音"},
        "target_duration_s": 36.0,
    }
    payload.update(overrides)
    return payload


class TestCompleteness:
    def test_full_expectation_is_accepted(self) -> None:
        digest = omni_expectation_contract_hash(_expectation())
        assert len(digest) == 64

    @pytest.mark.parametrize("part", EXPECTATION_REQUIRED_PARTS)
    def test_missing_part_is_rejected(self, part) -> None:
        payload = _expectation()
        del payload[part]
        with pytest.raises(ValueError):
            omni_expectation_contract_hash(payload)

    def test_unknown_part_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            omni_expectation_contract_hash(
                _expectation(extra_untracked_field=1)
            )


class TestOrderIndependence:
    def test_mapping_key_order_is_irrelevant(self) -> None:
        payload = _expectation()
        reversed_payload = dict(reversed(list(payload.items())))
        assert omni_expectation_contract_hash(
            payload
        ) == omni_expectation_contract_hash(reversed_payload)

    def test_speech_order_is_semantic(self) -> None:
        payload = _expectation()
        reversed_speech = _expectation(speech=list(reversed(payload["speech"])))
        assert omni_expectation_contract_hash(
            payload
        ) != omni_expectation_contract_hash(reversed_speech)

    def test_sound_event_timing_order_is_semantic(self) -> None:
        payload = _expectation()
        swapped = _expectation(
            sound_events=list(reversed(payload["sound_events"]))
        )
        assert omni_expectation_contract_hash(
            payload
        ) != omni_expectation_contract_hash(swapped)


class TestBindingSummaryConsistency:
    def test_binding_summary_derived_from_same_source(self) -> None:
        payload = _expectation()
        summary_hash = build_voice_binding_summary(
            payload["voice_binding_summary"]
        )
        rebuilt = build_voice_binding_summary(
            list(reversed(payload["voice_binding_summary"]))
        )
        # 绑定摘要独立保留供审计，但与期望合同来自同一规范化来源：
        # 同内容不同输入顺序得到同一摘要。
        assert summary_hash == rebuilt
        assert summary_hash
        # 期望合同内嵌的 binding summary 内容变化必须同时改变合同 hash。
        mutated = _expectation(
            voice_binding_summary=[
                {
                    "speaker": "弟子",
                    "slot_index": 1,
                    "reference_content_hash": "h-changed",
                },
            ]
        )
        assert omni_expectation_contract_hash(
            payload
        ) != omni_expectation_contract_hash(mutated)


class TestBinaryRejected:
    def test_binary_content_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            omni_expectation_contract_hash(
                _expectation(acoustic_treatment=[b"raw-bytes"])
            )
