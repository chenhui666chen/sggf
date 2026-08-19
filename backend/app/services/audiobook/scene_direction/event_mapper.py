"""event_mapper：导演计划 → 供应商中立 SceneAudioEvent[]（指导文档 §4.2）。

台词逐字来自审定事实源：按 source_segment_index 读取源片段的说话人与
台词，导演计划本身不携带台词副本。事件排序确定：carry-in 与
throughout 靠前，before 事件先于锚定台词，during/overlap 随台词，
after 事件随后，carry-out 收尾。同文件提供 §8.1 的确定性事件区间
时长估算器，不把所有音效 duration 简单相加。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple

from ..duration_estimator import estimate_narration_duration_seconds
from ..scene_engine.models import SceneAudioEvent
from .models import SeedSceneDirection, SeedSoundDirection, SeedSpeechDirection, SeedVocalizationDirection

ESTIMATOR_CONTRACT_VERSION = "1.0.0"

# duration 缺失的短触发音使用版本化保守默认值（§8.1）。
DEFAULT_SHORT_SOUND_DURATION_S = 1.5

# 导演 anchor → SceneAudioEvent anchor。
_ANCHOR_MAP = {
    "sequence": "during",
    "during": "during",
    "overlap": "during",
    "before": "before",
    "after": "after",
    "throughout": "throughout",
    "until_text": "until_text",
}

_BACKGROUND_PERFORMANCE_PREFIX = "背景层"


@dataclass(frozen=True)
class SceneDurationEstimate:
    speech_s: float
    pauses_s: float
    sequential_events_s: float
    overlap_tail_s: float
    total_s: float
    confidence: str


def map_direction_to_events(
    direction: SeedSceneDirection, segments: Sequence[Any]
) -> Tuple[SceneAudioEvent, ...]:
    """把已验证的导演计划映射为有序 SceneAudioEvent 序列。"""
    events: List[SceneAudioEvent] = []

    if direction.context.carry_in:
        events.append(
            SceneAudioEvent(
                kind="scene",
                anchor="before",
                acoustic="carry-in：" + "，".join(direction.context.carry_in),
            )
        )
    context_parts = [
        part
        for part in (
            direction.context.location,
            direction.context.acoustic_space,
            direction.context.ambient_state,
        )
        if part
    ]
    if context_parts:
        events.append(
            SceneAudioEvent(kind="scene", anchor="before", acoustic="，".join(context_parts))
        )

    sounds = list(direction.sounds)
    for sound in sounds:
        if sound.anchor == "throughout" and sound.relative_to_segment_index is None:
            events.append(_sound_event(sound))

    anchor_speeches = [
        speech
        for speech in direction.speech
        if speech.layer == "foreground" and speech.anchor == "sequence"
    ]
    anchor_speeches.sort(key=lambda speech: speech.source_segment_index)

    def tied(items: Sequence[Any], index: int, anchor: str) -> List[SceneAudioEvent]:
        return [
            _tied_event(item, segments)
            for item in items
            if item.relative_to_segment_index == index and item.anchor == anchor
        ]

    overlap_anchors = ("during", "overlap")
    for speech in anchor_speeches:
        index = speech.source_segment_index
        events.extend(tied(direction.vocalizations, index, "before"))
        events.extend(tied(sounds, index, "before"))
        events.extend(tied(_non_anchor_speeches(direction), index, "before"))
        events.append(_speech_event(speech, segments))
        for anchor in overlap_anchors:
            events.extend(tied(direction.vocalizations, index, anchor))
            events.extend(tied(sounds, index, anchor))
            events.extend(tied(_non_anchor_speeches(direction), index, anchor))
        events.extend(tied(direction.vocalizations, index, "after"))
        events.extend(tied(sounds, index, "after"))
        events.extend(tied(_non_anchor_speeches(direction), index, "after"))

    for sound in sounds:
        if sound.anchor == "until_text":
            events.append(_sound_event(sound))

    if direction.context.carry_out:
        events.append(
            SceneAudioEvent(
                kind="scene",
                anchor="after",
                acoustic="carry-out：" + "，".join(direction.context.carry_out),
            )
        )
    return tuple(events)


def estimate_scene_duration(
    direction: SeedSceneDirection, segments: Sequence[Any]
) -> SceneDurationEstimate:
    """确定性事件区间估算（§8.1）：不把音效 duration 简单相加。"""
    speech_s = 0.0
    for speech in direction.speech:
        if speech.layer == "foreground" and speech.anchor == "sequence":
            speech_s += _segment_speech_s(speech.source_segment_index, segments)

    pauses_s = 0.0
    for index in direction.source_segment_indices:
        pauses_s += _pause_seconds(segments[index], "pause_before")
        pauses_s += _pause_seconds(segments[index], "pause_after")

    sequential_s = 0.0
    missing_duration = False
    for sound in direction.sounds:
        if sound.anchor in ("before", "after"):
            duration = sound.duration_s
            if duration is None:
                duration = DEFAULT_SHORT_SOUND_DURATION_S
                missing_duration = True
            sequential_s += max(0.0, float(duration))
    for speech in direction.speech:
        if speech.anchor in ("before", "after") or (
            speech.layer == "background" and speech.anchor == "sequence"
        ):
            sequential_s += _segment_speech_s(speech.source_segment_index, segments)

    overlap_tail_s = 0.0
    for sound in direction.sounds:
        if sound.kind in ("music", "ambient"):
            continue  # 音乐与持续环境默认不增加场景总时长。
        if sound.anchor in ("during", "overlap", "throughout"):
            duration = sound.duration_s
            if duration is None:
                duration = DEFAULT_SHORT_SOUND_DURATION_S
                missing_duration = True
            base = _overlap_base_s(sound, direction, segments)
            overlap_tail_s += max(0.0, float(duration) - base)
    for speech in direction.speech:
        if speech.layer == "background" and speech.anchor in ("during", "overlap"):
            base = _segment_speech_s(speech.relative_to_segment_index or 0, segments)
            overlap_tail_s += max(
                0.0, _segment_speech_s(speech.source_segment_index, segments) - base
            )

    confidence = "conservative" if missing_duration else "high"
    total_s = speech_s + pauses_s + sequential_s + overlap_tail_s
    return SceneDurationEstimate(
        speech_s=round(speech_s, 3),
        pauses_s=round(pauses_s, 3),
        sequential_events_s=round(sequential_s, 3),
        overlap_tail_s=round(overlap_tail_s, 3),
        total_s=round(total_s, 3),
        confidence=confidence,
    )


# ---- 内部辅助 -----------------------------------------------------------


def _non_anchor_speeches(direction: SeedSceneDirection) -> Tuple[SeedSpeechDirection, ...]:
    return tuple(
        speech for speech in direction.speech if speech.anchor != "sequence"
    )


def _speech_event(speech: SeedSpeechDirection, segments: Sequence[Any]) -> SceneAudioEvent:
    segment = segments[speech.source_segment_index]
    performance = str(speech.performance or "").strip()
    if speech.layer == "background":
        performance = (
            f"{_BACKGROUND_PERFORMANCE_PREFIX}：{performance}" if performance else _BACKGROUND_PERFORMANCE_PREFIX
        )
    return SceneAudioEvent(
        kind="speech",
        anchor=_ANCHOR_MAP[speech.anchor],
        speaker=str(getattr(segment, "speaker", "") or speech.speaker),
        exact_text=str(getattr(segment, "text", "") or ""),
        performance=performance or None,
        acoustic=str(speech.acoustic or "").strip() or None,
    )


def _tied_event(item: Any, segments: Sequence[Any]) -> SceneAudioEvent:
    if isinstance(item, SeedVocalizationDirection):
        return _vocalization_event(item)
    if isinstance(item, SeedSoundDirection):
        return _sound_event(item)
    return _speech_event(item, segments)


def _vocalization_event(vocalization: SeedVocalizationDirection) -> SceneAudioEvent:
    performance = str(vocalization.description or "").strip()
    if vocalization.performance:
        performance = "，".join(part for part in (performance, vocalization.performance) if part)
    return SceneAudioEvent(
        kind="vocalization",
        anchor=_ANCHOR_MAP[vocalization.anchor],
        speaker=vocalization.speaker,
        performance=performance or None,
        acoustic=str(vocalization.acoustic or "").strip() or None,
    )


def _sound_event(sound: SeedSoundDirection) -> SceneAudioEvent:
    acoustic = str(sound.description or "").strip()
    if sound.delay_s > 0:
        acoustic = f"{acoustic}（延迟约{sound.delay_s:g}秒）" if acoustic else f"延迟约{sound.delay_s:g}秒"
    return SceneAudioEvent(
        kind=sound.kind,
        anchor=_ANCHOR_MAP[sound.anchor],
        acoustic=acoustic or None,
        related_text=str(sound.related_text or "").strip() or None,
    )


def _segment_speech_s(index: int, segments: Sequence[Any]) -> float:
    return estimate_narration_duration_seconds(
        str(getattr(segments[index], "text", "") or ""), min_duration=0.0
    )


def _overlap_base_s(
    sound: SeedSoundDirection, direction: SeedSceneDirection, segments: Sequence[Any]
) -> float:
    if sound.anchor == "throughout":
        return sum(
            _segment_speech_s(speech.source_segment_index, segments)
            for speech in direction.speech
            if speech.layer == "foreground" and speech.anchor == "sequence"
        )
    index = sound.relative_to_segment_index
    if index is None:
        return 0.0
    return _segment_speech_s(index, segments)


def _pause_seconds(segment: Any, field: str) -> float:
    value = getattr(segment, field, 0.0)
    voice_params = getattr(segment, "voice_params", None)
    if isinstance(voice_params, dict) and voice_params.get(field) is not None:
        value = voice_params[field]
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "DEFAULT_SHORT_SOUND_DURATION_S",
    "ESTIMATOR_CONTRACT_VERSION",
    "SceneDurationEstimate",
    "estimate_scene_duration",
    "map_direction_to_events",
]
