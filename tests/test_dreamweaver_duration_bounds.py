# -*- coding: utf-8 -*-
"""DreamWeaver 短剧时长边界放开到 wan3.0-video 官方区间 [2, 30] 整数秒。

覆盖四处历史“自造合法集”：
- `pipeline.media_presets.normalize_dreamweaver_video_duration_s` 的 {5,10,15} 最近档吸附
- `_duration._rebalance_storyboard_total_duration` 的 [5,10,15] 阶梯回压
- `_run` 在容器模式下把镜头上下界再夹进 5~15 的额外钳制
  （现已接回 `pipeline.media_presets.dreamweaver_beat_duration_bounds_s`，与剧本 beat 同源）
- `agents/scripter_pkg/_generate.build_system_prompt` 写死的「beat 时长 2-15s」提示词文案
  （现由 DREAMWEAVER_STORYBOARD_MIN/MAX_SHOT_S 与官方区间共同派生，见
  `pipeline.media_presets.dreamweaver_beat_duration_bounds_s`）
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]


# ============================================================
# 归一化：区间内保持、小数取整、越界夹取、非法回落
# ============================================================

@pytest.mark.parametrize(
    "seconds",
    [2.0, 3.0, 5.0, 7.0, 10.0, 12.0, 15.0, 20.0, 23.0, 30.0],
)
def test_integer_duration_inside_official_range_is_kept(seconds):
    from pipeline.media_presets import normalize_dreamweaver_video_duration_s

    assert normalize_dreamweaver_video_duration_s(seconds) == seconds


@pytest.mark.parametrize(
    "raw,expected",
    [(12.4, 12.0), (12.6, 13.0), (2.5, 3.0), (7.4, 7.0), (15.5, 16.0), (19.9, 20.0)],
)
def test_fractional_duration_rounds_half_up(raw, expected):
    from pipeline.media_presets import normalize_dreamweaver_video_duration_s

    assert normalize_dreamweaver_video_duration_s(raw) == expected


@pytest.mark.parametrize("raw,expected", [(1.0, 2.0), (0.5, 2.0), (45.0, 30.0), (99.0, 30.0)])
def test_duration_outside_official_range_is_clamped(raw, expected):
    from pipeline.media_presets import normalize_dreamweaver_video_duration_s

    assert normalize_dreamweaver_video_duration_s(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", 0, 0.0, -3.0])
def test_invalid_duration_falls_back_to_default(raw):
    from pipeline.media_presets import normalize_dreamweaver_video_duration_s

    assert normalize_dreamweaver_video_duration_s(raw, default=7.0) == 7.0


def test_legacy_discrete_duration_tiers_are_retired():
    import pipeline.media_presets as media_presets

    assert not hasattr(media_presets, "DREAMWEAVER_VIDEO_SUPPORTED_DURATIONS_S")


def test_duration_range_matches_wan3_adapter():
    from adapters.dashscope import video_wan3
    from pipeline.media_presets import (
        DREAMWEAVER_VIDEO_DURATION_MAX_S,
        DREAMWEAVER_VIDEO_DURATION_MIN_S,
    )

    assert DREAMWEAVER_VIDEO_DURATION_MIN_S == float(video_wan3.DURATION_MIN)
    assert DREAMWEAVER_VIDEO_DURATION_MAX_S == float(video_wan3.DURATION_MAX)


# ============================================================
# 总时长 rebalance：单轮 +5s/镜，上下界由官方区间给定
# ============================================================

def test_rebalance_grow_moves_five_seconds_per_shot():
    from agents.storyboarder_pkg._duration import _rebalance_storyboard_total_duration

    storyboard = [{"shot_id": "S1", "duration_s": 12.0, "desc": "急诊室夜景，护士走过走廊"}]
    result = _rebalance_storyboard_total_duration(
        storyboard,
        target_total_s=17.0,
        min_s=2.0,
        max_s=30.0,
        uses_video_containers=True,
        engine_label="wan_auto",
    )

    assert result["changed"] is True
    assert storyboard[0]["duration_s"] == 17.0


def test_rebalance_grow_stops_at_official_max():
    from agents.storyboarder_pkg._duration import _rebalance_storyboard_total_duration

    storyboard = [{"shot_id": "S1", "duration_s": 27.0, "desc": "天台对峙"}]
    _rebalance_storyboard_total_duration(
        storyboard,
        target_total_s=40.0,
        min_s=2.0,
        max_s=30.0,
        uses_video_containers=True,
        engine_label="wan_auto",
    )

    assert storyboard[0]["duration_s"] == 30.0


def test_rebalance_shrink_moves_five_seconds_down(monkeypatch):
    from agents.storyboarder_pkg._duration import _rebalance_storyboard_total_duration

    monkeypatch.setenv("DREAMWEAVER_WAN_I2V_REBALANCE_ALLOW_SHRINK", "1")
    storyboard = [{"shot_id": "S1", "duration_s": 12.0, "desc": "特写化验单"}]
    _rebalance_storyboard_total_duration(
        storyboard,
        target_total_s=7.0,
        min_s=2.0,
        max_s=30.0,
        uses_video_containers=True,
        engine_label="wan_auto",
    )

    assert storyboard[0]["duration_s"] == 7.0


# ============================================================
# 容器内 subshots：非经典档位也要覆盖整段，不留空白
# ============================================================

@pytest.mark.parametrize("duration", [7.0, 12.0, 20.0, 28.0, 30.0])
def test_fallback_subshots_cover_whole_container(duration):
    from agents.storyboarder_pkg._video_subshots import _fallback_video_subshots

    subshots = _fallback_video_subshots(
        duration_s=duration,
        ff_desc="走廊全景",
        lf_desc="化验单特写",
        visual_desc="护士走过走廊",
    )

    assert len(subshots) >= 2
    assert len(subshots) <= 6
    assert float(subshots[0]["start_s"]) == 0.0
    assert float(subshots[-1]["end_s"]) == duration
    for prev, nxt in zip(subshots, subshots[1:]):
        assert float(nxt["start_s"]) == float(prev["end_s"])


def test_fallback_subshots_keep_legacy_bins():
    from agents.storyboarder_pkg._video_subshots import _fallback_video_subshots

    kwargs = {"ff_desc": "", "lf_desc": "", "visual_desc": "夜班急诊"}
    assert [(s["start_s"], s["end_s"]) for s in _fallback_video_subshots(duration_s=5.0, **kwargs)] == [
        (0.0, 3.0),
        (3.0, 5.0),
    ]
    assert [(s["start_s"], s["end_s"]) for s in _fallback_video_subshots(duration_s=10.0, **kwargs)] == [
        (0.0, 4.0),
        (4.0, 7.0),
        (7.0, 10.0),
    ]
    assert [(s["start_s"], s["end_s"]) for s in _fallback_video_subshots(duration_s=15.0, **kwargs)] == [
        (0.0, 4.0),
        (4.0, 8.0),
        (8.0, 12.0),
        (12.0, 15.0),
    ]


# ============================================================
# 镜头上下界：只由官方区间归一化决定，不叠加自造的 5~15 合法上限
# ============================================================

def test_storyboard_shot_bounds_no_longer_clamped_to_legacy_window():
    source = (ROOT_DIR / "agents/storyboarder_pkg/_run.py").read_text(encoding="utf-8")

    # 五~十五的自造合法集不能以任何形式回来：叠加钳制、归一化的 5/15 兜底、env 的 5/15 默认值
    for legacy in (
        "normalize_dreamweaver_video_duration_s(max(5.0, min_shot_s)",
        "normalize_dreamweaver_video_duration_s(min(15.0, max_shot_s)",
        "normalize_dreamweaver_video_duration_s(min_shot_s, default=5.0)",
        "normalize_dreamweaver_video_duration_s(max_shot_s, default=15.0)",
        'DREAMWEAVER_STORYBOARD_MIN_SHOT_S", 5.0',
        'DREAMWEAVER_STORYBOARD_MAX_SHOT_S", 15.0',
    ):
        assert legacy not in source
    # 容器模式的镜头区间必须等于剧本 beat 的同一个派生函数，否则仍是第二个事实源
    assert "min_shot_s, max_shot_s = dreamweaver_beat_duration_bounds_s()" in source
    assert "    dreamweaver_beat_duration_bounds_s,\n" in source


# ============================================================
# 提示词文案：beat 时长区间由 env + 官方区间派生，不再写死 2-15s
# ============================================================

def test_beat_prompt_duration_range_follows_env(monkeypatch):
    from agents.scripter_pkg._generate import build_system_prompt

    monkeypatch.setenv("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", "3.0")
    monkeypatch.setenv("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", "12.0")
    prompt = build_system_prompt({})
    assert "beat 时长 3-12s" in prompt
    assert "2-15s" not in prompt


def test_beat_prompt_duration_range_defaults_to_official_bounds(monkeypatch):
    from agents.scripter_pkg._generate import build_system_prompt

    monkeypatch.delenv("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", raising=False)
    monkeypatch.delenv("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", raising=False)
    assert "beat 时长 2-30s" in build_system_prompt({})


@pytest.mark.parametrize(
    "low,high,expected",
    [("1", "99", (2.0, 30.0)), ("", "", (2.0, 30.0)), ("abc", "xyz", (2.0, 30.0))],
)
def test_beat_prompt_bounds_never_leave_official_range(monkeypatch, low, high, expected):
    from pipeline.media_presets import dreamweaver_beat_duration_bounds_s

    monkeypatch.setenv("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", low)
    monkeypatch.setenv("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", high)
    assert dreamweaver_beat_duration_bounds_s() == expected


def test_beat_prompt_bounds_reject_inverted_env(monkeypatch):
    from pipeline.media_presets import dreamweaver_beat_duration_bounds_s

    monkeypatch.setenv("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", "20")
    monkeypatch.setenv("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", "4")
    low, high = dreamweaver_beat_duration_bounds_s()
    assert low <= high
