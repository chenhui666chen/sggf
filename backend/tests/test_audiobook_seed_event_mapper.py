"""阶段 4 event_mapper 测试：导演计划 → 供应商中立 SceneAudioEvent[]。

覆盖指导文档 §4.2（event_mapper 职责）、§8.1（事件区间时长估算）、
§9.1（固定结构）与阶段 4 验收：

- 台词逐字来自审定事实源（按 source_segment_index 读源片段，
  导演计划不携带台词副本）；
- speech/vocalization/sfx/music/transition 显式导演事件全部映射；
- 事件排序确定：before 事件先于锚定台词、during/overlap 随台词、
  after 事件随后；throughout 与 carry-in 靠前、carry-out 收尾；
- 事件区间估算器不把所有音效 duration 简单相加：
  before/after 独占、during/throughout/overlap 只计超出部分、
  音乐与持续环境不增加总时长、缺失 duration 用版本化保守默认值；
- 背景 speech 按与前景关系计算重叠或独占区间。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_direction.event_mapper import (  # noqa: E402
    ESTIMATOR_CONTRACT_VERSION,
    SceneDurationEstimate,
    estimate_scene_duration,
    map_direction_to_events,
)
from app.services.audiobook.scene_direction.models import (  # noqa: E402
    SeedSceneContext,
    SeedSceneDirection,
    SeedSoundDirection,
    SeedSpeechDirection,
    SeedVocalizationDirection,
    SegmentEvidenceRef,
)


def _segments():
    return [
        SimpleNamespace(text="我们先检查一下现场。", speaker="林川", pause_before=0.0, pause_after=0.5),
        SimpleNamespace(text="好，我负责东侧。", speaker="苏眠", pause_before=0.3, pause_after=0.0),
        SimpleNamespace(text="注意保持安静。", speaker="林川", pause_before=0.0, pause_after=0.0),
    ]


def _evidence(segment_index=0) -> SegmentEvidenceRef:
    return SegmentEvidenceRef(segment_index=segment_index, field="text", excerpt="检查")


def _direction(**overrides) -> SeedSceneDirection:
    defaults = dict(
        scene_key="scene_0001",
        source_segment_indices=(0, 1, 2),
        context=SeedSceneContext(
            location="废弃仓库",
            acoustic_space="空旷回声",
            ambient_state="远处风声",
            carry_in=("低频风声持续",),
            carry_out=("脚步声渐远",),
        ),
        speech=(
            SeedSpeechDirection(source_segment_index=0, speaker="林川", performance="压低声音"),
            SeedSpeechDirection(source_segment_index=1, speaker="苏眠"),
            SeedSpeechDirection(source_segment_index=2, speaker="林川"),
        ),
        vocalizations=(),
        sounds=(),
        timeline_mode="natural",
    )
    defaults.update(overrides)
    return SeedSceneDirection(**defaults)


class TestSpeechMapping:
    def test_speech_text_and_speaker_come_from_source_segments(self):
        events = map_direction_to_events(_direction(), _segments())
        speeches = [event for event in events if event.kind == "speech"]
        assert [event.exact_text for event in speeches] == [
            "我们先检查一下现场。",
            "好，我负责东侧。",
            "注意保持安静。",
        ]
        assert [event.speaker for event in speeches] == ["林川", "苏眠", "林川"]

    def test_sequential_foreground_speech_uses_during_anchor(self):
        events = map_direction_to_events(_direction(), _segments())
        speeches = [event for event in events if event.kind == "speech"]
        assert all(event.anchor == "during" for event in speeches)

    def test_background_speech_keeps_text_and_marks_layer(self):
        direction = _direction(
            speech=_direction().speech
            + (
                SeedSpeechDirection(
                    source_segment_index=1,
                    speaker="苏眠",
                    layer="background",
                    anchor="during",
                    relative_to_segment_index=0,
                ),
            )
        )
        events = map_direction_to_events(direction, _segments())
        background = [
            event
            for event in events
            if event.kind == "speech" and event.exact_text == "好，我负责东侧。"
        ]
        assert len(background) == 2  # 前景一次 + 背景一次
        background_event = [event for event in background if "背景" in (event.performance or "")]
        assert len(background_event) == 1

    def test_overlap_anchor_maps_to_during(self):
        direction = _direction(
            speech=_direction().speech
            + (
                SeedSpeechDirection(
                    source_segment_index=2,
                    speaker="林川",
                    anchor="overlap",
                    relative_to_segment_index=1,
                ),
            )
        )
        events = map_direction_to_events(direction, _segments())
        overlapping = [event for event in events if event.kind == "speech"][-1]
        assert overlapping.anchor == "during"


class TestVocalizationAndSoundMapping:
    def test_vocalization_maps_without_text(self):
        direction = _direction(
            vocalizations=(
                SeedVocalizationDirection(
                    speaker="苏眠",
                    description="倒吸一口冷气",
                    anchor="before",
                    relative_to_segment_index=1,
                    evidence=_evidence(1),
                ),
            )
        )
        events = map_direction_to_events(direction, _segments())
        vocal = [event for event in events if event.kind == "vocalization"]
        assert len(vocal) == 1
        assert vocal[0].anchor == "before"
        assert vocal[0].speaker == "苏眠"
        assert vocal[0].exact_text is None
        assert "倒吸一口冷气" in (vocal[0].performance or "")

    def test_until_text_sound_carries_related_text(self):
        direction = _direction(
            sounds=(
                SeedSoundDirection(
                    kind="sfx",
                    description="金属门关闭",
                    anchor="until_text",
                    relative_to_segment_index=0,
                    related_text="我们先检查一下现场。",
                    duration_s=2.0,
                ),
            )
        )
        events = map_direction_to_events(direction, _segments())
        sfx = [event for event in events if event.kind == "sfx"]
        assert sfx[0].anchor == "until_text"
        assert sfx[0].related_text == "我们先检查一下现场。"

    def test_montage_sequence_group_preserves_order(self):
        direction = _direction(
            sounds=(
                SeedSoundDirection(kind="sfx", description="脚步声", anchor="before", relative_to_segment_index=0, sequence_group="approach", duration_s=1.0),
                SeedSoundDirection(kind="sfx", description="开门声", anchor="before", relative_to_segment_index=0, sequence_group="approach", duration_s=0.8),
            )
        )
        events = map_direction_to_events(direction, _segments())
        sfx = [event.acoustic for event in events if event.kind == "sfx"]
        assert sfx == ["脚步声", "开门声"]


class TestEventOrderingAndCarryState:
    def test_carry_in_first_and_carry_out_last(self):
        events = map_direction_to_events(_direction(), _segments())
        assert events[0].kind == "scene"
        assert "低频风声持续" in (events[0].acoustic or "")
        assert events[-1].kind == "scene"
        assert "脚步声渐远" in (events[-1].acoustic or "")

    def test_before_during_after_around_anchor_speech(self):
        direction = _direction(
            vocalizations=(
                SeedVocalizationDirection(
                    speaker="苏眠",
                    description="轻声吸气",
                    anchor="before",
                    relative_to_segment_index=1,
                    evidence=_evidence(1),
                ),
            ),
            sounds=(
                SeedSoundDirection(kind="sfx", description="纸张翻动", anchor="during", relative_to_segment_index=1, duration_s=1.0),
                SeedSoundDirection(kind="sfx", description="椅子轻响", anchor="after", relative_to_segment_index=1, duration_s=0.5),
            ),
        )
        events = map_direction_to_events(direction, _segments())
        sequence = [event.kind for event in events]
        vocalization_index = sequence.index("vocalization")
        anchor_index = [
            index
            for index, event in enumerate(events)
            if event.kind == "speech" and event.exact_text == "好，我负责东侧。"
        ][0]
        during_index = sequence.index("sfx")
        after_index = len(sequence) - 1 - sequence[::-1].index("sfx")
        assert vocalization_index < anchor_index < during_index < after_index

    def test_mapping_is_deterministic(self):
        direction = _direction()
        assert map_direction_to_events(direction, _segments()) == map_direction_to_events(
            direction, _segments()
        )


class TestDurationEstimation:
    def test_estimate_structure_and_totals(self):
        estimate = estimate_scene_duration(_direction(), _segments())
        assert isinstance(estimate, SceneDurationEstimate)
        assert estimate.speech_s > 0
        assert estimate.pauses_s == 0.8  # 0.5 + 0.3
        assert estimate.total_s == round(
            estimate.speech_s + estimate.pauses_s + estimate.sequential_events_s + estimate.overlap_tail_s,
            3,
        )

    def test_music_and_ambient_do_not_extend_scene(self):
        base = estimate_scene_duration(_direction(), _segments())
        with_music = estimate_scene_duration(
            _direction(
                sounds=(
                    SeedSoundDirection(kind="music", description="紧张弦乐", anchor="throughout", duration_s=60.0),
                    SeedSoundDirection(kind="ambient", description="远处风声", anchor="throughout", duration_s=60.0),
                )
            ),
            _segments(),
        )
        assert with_music.total_s == base.total_s

    def test_before_after_sfx_add_exclusive_duration(self):
        base = estimate_scene_duration(_direction(), _segments())
        with_sfx = estimate_scene_duration(
            _direction(
                sounds=(
                    SeedSoundDirection(kind="sfx", description="开门声", anchor="before", relative_to_segment_index=0, duration_s=1.5),
                    SeedSoundDirection(kind="sfx", description="关门声", anchor="after", relative_to_segment_index=2, duration_s=1.0),
                )
            ),
            _segments(),
        )
        assert with_sfx.sequential_events_s == base.sequential_events_s + 2.5
        assert with_sfx.total_s == base.total_s + 2.5

    def test_missing_duration_uses_versioned_conservative_default(self):
        with_default = estimate_scene_duration(
            _direction(
                sounds=(SeedSoundDirection(kind="sfx", description="玻璃碎裂", anchor="before", relative_to_segment_index=0),)
            ),
            _segments(),
        )
        assert with_default.sequential_events_s > 0
        assert with_default.confidence == "conservative"

    def test_during_sfx_only_adds_tail_beyond_anchor_speech(self):
        segments = _segments()
        anchor_speech_s = len(segments[0].text) / 4.5  # 与估算器同口径
        short = estimate_scene_duration(
            _direction(
                sounds=(SeedSoundDirection(kind="sfx", description="轻响", anchor="during", relative_to_segment_index=0, duration_s=0.5),)
            ),
            segments,
        )
        base = estimate_scene_duration(_direction(), segments)
        assert short.total_s == base.total_s  # 完全被台词覆盖，不增加
        long = estimate_scene_duration(
            _direction(
                sounds=(SeedSoundDirection(kind="sfx", description="长警报", anchor="during", relative_to_segment_index=0, duration_s=anchor_speech_s + 3.0),)
            ),
            segments,
        )
        assert round(long.overlap_tail_s, 3) == 3.0

    def test_background_sequence_speech_adds_exclusive_duration(self):
        direction = _direction(
            speech=_direction().speech
            + (
                SeedSpeechDirection(
                    source_segment_index=1,
                    speaker="苏眠",
                    layer="background",
                    anchor="before",
                    relative_to_segment_index=0,
                ),
            )
        )
        base = estimate_scene_duration(_direction(), _segments())
        estimate = estimate_scene_duration(direction, _segments())
        assert estimate.sequential_events_s > base.sequential_events_s

    def test_sequence_group_accumulates_sequentially(self):
        direction = _direction(
            sounds=(
                SeedSoundDirection(kind="sfx", description="脚步声", anchor="before", relative_to_segment_index=0, sequence_group="approach", duration_s=1.0),
                SeedSoundDirection(kind="sfx", description="开门声", anchor="before", relative_to_segment_index=0, sequence_group="approach", duration_s=0.8),
            )
        )
        estimate = estimate_scene_duration(direction, _segments())
        assert estimate.sequential_events_s == 1.8

    def test_confidence_high_when_all_durations_explicit(self):
        estimate = estimate_scene_duration(
            _direction(
                sounds=(SeedSoundDirection(kind="sfx", description="开门声", anchor="before", relative_to_segment_index=0, duration_s=1.0),)
            ),
            _segments(),
        )
        assert estimate.confidence == "high"

    def test_estimator_contract_version_exposed(self):
        assert ESTIMATOR_CONTRACT_VERSION == "1.0.0"
