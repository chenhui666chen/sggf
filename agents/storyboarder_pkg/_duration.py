from __future__ import annotations

import difflib
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.storyboarder_pkg._env_helpers import (
    _count_script_beats,
    _count_script_scenes,
    _count_source_chars,
    _env_float,
    _env_int,
)
from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_tree, build_camera_tree_llm
from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model, llm_stream_context
from pipeline.media_presets import (
    DREAMWEAVER_AUTO_ENGINE,
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    ensure_media_payload,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
    normalize_frame_ratio,
)
from pipeline.style_presets import ensure_style_payload

# 容器模式下，单轮 rebalance 每个镜头最多推进 5 秒，避免一次改动过多镜头时长。
_CONTAINER_REBALANCE_STEP_S = 5.0


def _sum_storyboard_duration_s(storyboard: Any) -> float:
    if not isinstance(storyboard, list):
        return 0.0
    total = 0.0
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        try:
            d = float(item.get("duration_s") or 0.0)
        except Exception:  # noqa: BLE001
            d = 0.0
        if d > 0.0:
            total += d
    return float(round(total, 1))


def _rebalance_storyboard_total_duration(
    storyboard: Any,
    *,
    target_total_s: Optional[float],
    min_s: float,
    max_s: float,
    uses_video_containers: bool,
    engine_label: str,
    tolerance: float = 0.15,
) -> Dict[str, Any]:
    if not isinstance(storyboard, list) or not storyboard:
        return {"enabled": False}
    if target_total_s is None or float(target_total_s) <= 0.0:
        return {"enabled": False}

    target = float(target_total_s)
    tol = float(tolerance) if tolerance and tolerance > 0 else 0.15
    before = _sum_storyboard_duration_s(storyboard)
    low = target * (1.0 - tol)
    high = target * (1.0 + tol)
    if low <= before <= high:
        return {"enabled": True, "changed": False, "target_total_s": target, "before_total_s": before, "after_total_s": before}

    changed = False
    min_v = float(min_s)
    max_v = float(max_s)
    if max_v < min_v:
        max_v = min_v

    def _weight(it: Dict[str, Any]) -> int:
        return len(str(it.get("desc") or "")) + len(str(it.get("visual_desc") or ""))

    if before < low:
        delta = target - before
        if uses_video_containers:
            idxs = sorted(range(len(storyboard)), key=lambda i: _weight(storyboard[i]) if isinstance(storyboard[i], dict) else 0, reverse=True)
            for i in idxs:
                if delta <= 1e-6:
                    break
                it = storyboard[i]
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                cur = normalize_dreamweaver_video_duration_s(cur if cur > 0.0 else min_v, default=min_v)
                nxt = normalize_dreamweaver_video_duration_s(min(cur + _CONTAINER_REBALANCE_STEP_S, max_v), default=cur)
                if nxt <= cur:
                    continue
                it["duration_s"] = float(nxt)
                delta -= float(nxt - cur)
                changed = True
        else:
            durations: List[Tuple[int, float, float]] = []
            for idx, it in enumerate(storyboard):
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                cur = max(min_v, min(max_v, cur if cur > 0 else min_v))
                headroom = max_v - cur
                if headroom > 1e-6:
                    durations.append((idx, cur, headroom))
            cap = sum(hr for _idx, _cur, hr in durations)
            if cap > 1e-6:
                for idx, cur, headroom in durations:
                    inc = delta * (headroom / cap)
                    if inc > headroom:
                        inc = headroom
                    new_v = cur + inc
                    if new_v > max_v:
                        new_v = max_v
                    storyboard[idx]["duration_s"] = round(float(new_v), 1)
                changed = True

    if before > high:
        delta = before - target
        if uses_video_containers:
            # 一致性优先：默认不做“缩短总时长”的回压，避免把已规划好的长容器切碎。
            # 若需要成本控制，可显式开启该开关。
            if not env_flag("DREAMWEAVER_WAN_I2V_REBALANCE_ALLOW_SHRINK", default=False):
                delta = 0.0
            if delta <= 1e-6:
                after = _sum_storyboard_duration_s(storyboard)
                return {
                    "enabled": True,
                    "changed": False,
                    "target_total_s": target,
                    "before_total_s": before,
                    "after_total_s": after,
                    "tolerance": tol,
                    "mode": str(engine_label or DREAMWEAVER_I2V_ENGINE),
                    "note": "skip_shrink",
                }
            idxs = sorted(range(len(storyboard)), key=lambda i: _weight(storyboard[i]) if isinstance(storyboard[i], dict) else 0)
            for i in idxs:
                if delta <= 1e-6:
                    break
                it = storyboard[i]
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                cur = normalize_dreamweaver_video_duration_s(cur if cur > 0.0 else min_v, default=min_v)
                nxt = normalize_dreamweaver_video_duration_s(max(cur - _CONTAINER_REBALANCE_STEP_S, min_v), default=cur)
                if nxt >= cur:
                    continue
                it["duration_s"] = float(nxt)
                delta -= float(cur - nxt)
                changed = True
        else:
            durations = []
            for idx, it in enumerate(storyboard):
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                cur = max(min_v, min(max_v, cur if cur > 0 else min_v))
                reducible = cur - min_v
                if reducible > 1e-6:
                    durations.append((idx, cur, reducible))
            cap = sum(rd for _idx, _cur, rd in durations)
            if cap > 1e-6:
                for idx, cur, reducible in durations:
                    dec = delta * (reducible / cap)
                    if dec > reducible:
                        dec = reducible
                    new_v = cur - dec
                    if new_v < min_v:
                        new_v = min_v
                    storyboard[idx]["duration_s"] = round(float(new_v), 1)
                changed = True

    after = _sum_storyboard_duration_s(storyboard)
    return {
        "enabled": True,
        "changed": bool(changed),
        "target_total_s": target,
        "before_total_s": before,
        "after_total_s": after,
        "tolerance": tol,
        "mode": str(engine_label or (DREAMWEAVER_I2V_ENGINE if uses_video_containers else "continuous")),
    }


def _storyboard_too_short_reason(
    storyboard: Any,
    *,
    min_shots_hint: int,
    target_total_s: Optional[float],
    tolerance: float = 0.2,
) -> str:
    if not isinstance(storyboard, list) or not storyboard:
        return "empty storyboard"
    min_shots = max(0, int(min_shots_hint))
    if min_shots > 0 and len(storyboard) < min_shots:
        return f"shots {len(storyboard)} < hint {min_shots}"
    if target_total_s is None or float(target_total_s) <= 0.0:
        return ""
    total = _sum_storyboard_duration_s(storyboard)
    target = float(target_total_s)
    tol = float(tolerance) if tolerance and tolerance > 0 else 0.2
    if total < target * (1.0 - tol):
        return f"total_duration_s {total} < {(target * (1.0 - tol)):.1f}"
    return ""


def _auto_max_shots_from_script(*, script_text: str, quality_mode: str) -> int:
    text = str(script_text or "")
    scenes = max(1, int(_count_script_scenes(text)))
    beats = max(0, int(_count_script_beats(text)))
    char_count = _count_source_chars(text)

    mode = str(quality_mode or "").strip().lower()
    if mode == "quality":
        per_scene_floor = scenes * 2
        base = 12
        chars_per_shot = 140
        hard_cap = 240
    else:
        per_scene_floor = scenes * 1
        base = 8
        chars_per_shot = 240
        hard_cap = 120

    estimated_by_chars = max(1, int(math.ceil(float(char_count) / float(max(60, int(chars_per_shot))))))
    estimated = max(int(base), int(per_scene_floor), int(beats), int(estimated_by_chars))
    return int(min(int(hard_cap), int(estimated)))


def _storyboard_safety_max_shots(*, quality_mode: str) -> int:
    """
    防止 LLM 生成无限长 JSON 导致内存/耗时不可控的“安全上限”。
    - 不建议把它理解为业务上限；更像是系统保护阈值。
    """
    default = 240 if str(quality_mode or "").strip().lower() == "quality" else 120
    return max(1, int(_env_int("DREAMWEAVER_STORYBOARD_SAFETY_MAX_SHOTS", default)))


def _estimate_shot_duration_s(text: str, *, min_s: float, max_s: float, base_s: float, cps: float) -> float:
    """
    根据文本长度估算镜头时长，解决“默认3秒导致整体过短”的问题。
    - min_s/max_s：避免极端值（I2V 通常也有时长上限）
    - base_s：镜头基础时长
    - cps：chars-per-second，控制节奏（越大越快）
    """
    cleaned = re.sub(r"\s+", "", str(text or ""))
    char_count = len(cleaned)
    safe_cps = cps if cps and cps > 0 else 20.0
    duration = float(base_s) + (float(char_count) / float(safe_cps))
    if duration < float(min_s):
        duration = float(min_s)
    if duration > float(max_s):
        duration = float(max_s)
    return round(duration, 1)


def _auto_adjust_storyboard_durations(storyboard: Any, *, min_s: float, max_s: float, base_s: float, cps: float) -> None:
    """
    统一修正 LLM/规则输出的 duration_s：
    - 缺失/非法：使用估算值
    - 低于下限：抬到下限
    - 高于上限：压到上限（避免 I2V 不支持的过长镜头）
    - 若看起来是默认值 3.0：允许按估算拉长（但不缩短）
    """
    if not isinstance(storyboard, list):
        return
    min_v = float(min_s)
    max_v = float(max_s)
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        raw = item.get("duration_s")
        try:
            cur = float(raw) if raw is not None else None
        except Exception:  # noqa: BLE001
            cur = None

        est = _estimate_shot_duration_s(str(item.get("desc") or ""), min_s=min_v, max_s=max_v, base_s=base_s, cps=cps)
        if cur is None or cur <= 0:
            item["duration_s"] = est
            continue
        if cur < min_v:
            item["duration_s"] = min_v
            continue
        if cur > max_v:
            item["duration_s"] = max_v
            continue
        if abs(cur - 3.0) < 1e-6 and est > cur:
            item["duration_s"] = est


def _clamp_01(value: Any, default: float = 0.5) -> float:
    try:
        v = float(value)
    except Exception:  # noqa: BLE001
        return default
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


