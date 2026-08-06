"""管线生成音效/配乐的按片段实时试听渲染。

管线只把章节级音效/配乐时间线固化在 run checkpoint（``effect_timeline`` /
``music_timeline``），并不按片段持久化分轨资产。工作台试听从最新时间线中
取归属目标片段的条目，按片段时长静音底轨叠加，复用与整章混音完全一致
的引擎叠加实现（音量增益、淡入淡出、循环、智能配乐平衡），保证试听结果
与章节成品一致。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.audiobook.audio_mixer import AudioMixer
from app.services.audiobook.engine_pkg._music_mixin import MusicMixin
from app.services.audiobook.engine_pkg._sfx_mixin import SfxMixin

logger = logging.getLogger(__name__)

_SEGMENT_TIMELINE_PREVIEW_KEYS = {
    "sfx": "effect_timeline",
    "bgm": "music_timeline",
}


class _TimelinePreviewRenderer(SfxMixin, MusicMixin):
    """复用引擎音效/配乐叠加实现，仅持有混音器与音效配置。"""

    def __init__(
        self,
        *,
        audio_fx: Optional[Dict[str, Any]] = None,
        audio_mixer: Optional[Any] = None,
    ) -> None:
        self.audio_mixer = audio_mixer or AudioMixer()
        self._audio_fx_config = dict(audio_fx or {})


def _segment_window(
    segment_timings: Any,
    segment_index: int,
) -> Optional[Tuple[float, float]]:
    """从章节时间轴取目标片段的 (start, end) 秒级窗口。"""
    if not isinstance(segment_timings, list):
        return None
    for fallback_index, timing in enumerate(segment_timings):
        if not isinstance(timing, dict):
            continue
        try:
            index = int(timing.get("index", fallback_index))
        except (TypeError, ValueError):
            index = fallback_index
        if index != segment_index:
            continue
        try:
            start = float(timing.get("start") or 0.0)
            end = float(timing.get("end") or 0.0)
        except (TypeError, ValueError):
            continue
        if end <= start:
            try:
                end = start + max(0.0, float(timing.get("duration") or 0.0))
            except (TypeError, ValueError):
                continue
        if end <= start:
            return None
        return start, end
    return None


def _collect_segment_timeline_items(
    items: List[Any],
    *,
    start: float,
    end: float,
    include_continuations: bool = False,
) -> List[Dict[str, Any]]:
    """取归属片段窗口的条目，时间戳转为片段内相对时间。

    默认只取触发时刻落在窗口内的条目；``include_continuations`` 额外纳入
    窗口前触发但仍在播放的延续条目（配乐跨场景持续），延续条目从片段
    开头播放剩余时长并去掉淡入（淡入已在原触发点完成）。
    循环/长素材一律截断到片段窗口内，避免试听音频远长于片段本身。
    """
    selected: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            timestamp = float(item.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        try:
            duration_val = (
                float(item.get("duration"))
                if item.get("duration") is not None
                else None
            )
        except (TypeError, ValueError):
            duration_val = None

        is_continuation = (
            include_continuations
            and timestamp < start
            and duration_val is not None
            and timestamp + duration_val > start
        )
        if not is_continuation and not (start <= timestamp < end):
            continue

        shifted = dict(item)
        if is_continuation:
            consumed = start - timestamp
            shifted["timestamp"] = 0.0
            shifted["fade_in"] = 0.0
            # 剩余时长仍截断到片段窗口，试听音频不跨片段
            remaining = max(0.5, min(duration_val - consumed, end - start))
        else:
            shifted["timestamp"] = round(timestamp - start, 3)
            remaining = end - timestamp
            if duration_val is None:
                remaining = min(remaining, end - start)
        if duration_val is None or duration_val > remaining:
            shifted["duration"] = round(max(0.5, remaining), 3)
        selected.append(shifted)
    return selected


def render_segment_timeline_preview(
    *,
    checkpoint: Dict[str, Any],
    segment_index: int,
    preview_type: str,
    audio_fx: Optional[Dict[str, Any]] = None,
    audio_mixer: Optional[Any] = None,
) -> Optional[bytes]:
    """按 checkpoint 时间线渲染单片段音效/配乐试听音频。

    无可归属该片段时间线条目、缺少片段时间轴或混音组件不可用时返回 None。
    """
    timeline_key = _SEGMENT_TIMELINE_PREVIEW_KEYS.get(
        str(preview_type or "").strip().lower()
    )
    if not timeline_key or not isinstance(checkpoint, dict):
        return None

    window = _segment_window(checkpoint.get("segment_timings"), segment_index)
    if window is None:
        return None
    start, end = window

    timeline_container = checkpoint.get(timeline_key)
    items = (
        timeline_container.get("timeline")
        if isinstance(timeline_container, dict)
        else None
    )
    if not isinstance(items, list):
        return None

    selected = _collect_segment_timeline_items(
        items,
        start=start,
        end=end,
        # 配乐常跨片段持续播放：延续中的 cue 也应可在后续片段试听
        include_continuations=(timeline_key == "music_timeline"),
    )
    if not selected:
        return None

    renderer = _TimelinePreviewRenderer(audio_fx=audio_fx, audio_mixer=audio_mixer)
    duration_ms = max(1000, int(round((end - start) * 1000)))
    try:
        base_audio = renderer.audio_mixer.create_silence(
            duration_ms,
            output_format="mp3",
            bitrate="128k",
        )
    except Exception as exc:
        logger.warning("时间线试听生成静音底轨失败: %s", exc)
        return None
    if not base_audio:
        return None

    try:
        if timeline_key == "effect_timeline":
            return renderer._apply_sound_effects(base_audio, {"timeline": selected})
        return renderer._apply_background_music(base_audio, {"timeline": selected})
    except Exception as exc:
        logger.warning(
            "时间线试听渲染失败: segment_index=%s preview_type=%s error=%s",
            segment_index,
            preview_type,
            exc,
        )
        return None
