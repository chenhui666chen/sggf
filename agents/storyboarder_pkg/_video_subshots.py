from __future__ import annotations

import difflib
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

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

def _safe_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _normalize_video_subshots(subshots: Any, *, duration_s: float) -> List[Dict[str, Any]]:
    """
    归一化 Wan I2V 的容器内子分镜时间轴。

    目标：
    - 覆盖 [0, duration_s]，无重叠、无空洞（会做轻量修正）
    - start_s/end_s 为数字，且 0<=start<end<=duration_s
    """
    try:
        duration = float(duration_s)
    except Exception:  # noqa: BLE001
        return []
    if duration <= 0.0:
        return []

    if not isinstance(subshots, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for raw in subshots:
        if not isinstance(raw, dict):
            continue
        start = _safe_float(raw.get("start_s"))
        end = _safe_float(raw.get("end_s"))
        if start is None or end is None:
            continue
        if end <= start:
            continue
        # 轻量截断到容器范围内
        start = max(0.0, min(float(start), duration))
        end = max(0.0, min(float(end), duration))
        if end <= start:
            continue

        item: Dict[str, Any] = {
            "start_s": round(float(start), 3),
            "end_s": round(float(end), 3),
        }
        for key in ("transition", "shot_type", "camera_angle", "camera_movement", "emotion", "desc", "visual_desc"):
            val = raw.get(key)
            if isinstance(val, (str, int, float)):
                s = str(val).strip()
                if s:
                    item[key] = s
        cleaned.append(item)
        if len(cleaned) >= 12:
            break

    if not cleaned:
        return []

    cleaned.sort(key=lambda x: float(x.get("start_s") or 0.0))

    # 修正：消除重叠，并尽量保证连续。
    normalized: List[Dict[str, Any]] = []
    cursor = 0.0
    for raw in cleaned:
        start = float(raw["start_s"])
        end = float(raw["end_s"])
        if end <= cursor:
            continue
        if start < cursor:
            start = cursor
        if start > cursor + 1e-3:
            # 有空洞：向前贴齐，避免出现不可控的“空白时间段”
            start = cursor
        if end <= start:
            continue
        item = dict(raw)
        item["start_s"] = round(float(start), 3)
        item["end_s"] = round(float(end), 3)
        normalized.append(item)
        cursor = float(end)
        if cursor >= duration - 1e-3:
            break

    if not normalized:
        return []

    # 对齐起止：确保覆盖完整容器
    normalized[0]["start_s"] = 0.0
    normalized[-1]["end_s"] = round(duration, 3)

    # 过多子分镜会导致 prompt 过长：保守裁剪为最多 6 段（优先保留首尾）
    if len(normalized) > 6:
        head = normalized[0]
        tail = normalized[-1]
        middle = normalized[1:-1]
        keep_mid = middle[: max(0, 4 - 2)]
        normalized = [head] + keep_mid + [tail]
        # 重算时间轴：按顺序等分填满，避免因裁剪导致空洞
        segments = len(normalized)
        if segments >= 2:
            step = duration / float(segments)
            for idx, it in enumerate(normalized):
                s = round(float(idx) * step, 3)
                e = round(float(idx + 1) * step, 3)
                it["start_s"] = 0.0 if idx == 0 else s
                it["end_s"] = round(duration, 3) if idx == segments - 1 else e

    return normalized


def _fallback_bins_for_duration(duration: float) -> List[Tuple[float, float]]:
    """非经典档位（5/10/15 之外）的保底时间戳：按约 5 秒一段均分，整数边界保证段间无空洞。"""
    total = int(max(1, round(float(duration))))
    segments = int(total / 5.0 + 0.5)
    segments = max(2, min(6, segments))
    while segments > 1 and segments * 2 > total:
        segments -= 1
    per_segment = _allocate_integer_durations(
        total_s=total,
        weights=[1.0] * segments,
        min_s=2,
        max_s=max(2, int(math.ceil(total / float(segments)))),
    )
    bins: List[Tuple[float, float]] = []
    cursor = 0
    for seg in per_segment:
        end = min(total, cursor + int(seg))
        if end > cursor:
            bins.append((float(cursor), float(end)))
        cursor = end
    if not bins:
        return [(0.0, float(total))]
    bins[-1] = (bins[-1][0], float(total))
    return bins


def _fallback_video_subshots(*, duration_s: float, ff_desc: str, lf_desc: str, visual_desc: str) -> List[Dict[str, Any]]:
    """
    LLM 未输出 subshots 时的保底分解策略：保证时间戳可用，但不替代 LLM 的真实分镜设计。
    """
    duration = normalize_dreamweaver_video_duration_s(duration_s, default=15.0)
    if duration == 5.0:
        bins = [(0.0, 3.0), (3.0, 5.0)]
        types = ["wide_shot", "close_up"]
    elif duration == 10.0:
        bins = [(0.0, 4.0), (4.0, 7.0), (7.0, 10.0)]
        types = ["wide_shot", "medium_shot", "close_up"]
    elif duration == 15.0:
        bins = [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0), (12.0, 15.0)]
        types = ["wide_shot", "medium_shot", "medium_shot", "close_up"]
    else:
        bins = _fallback_bins_for_duration(duration)
        types = ["wide_shot"] + ["medium_shot"] * max(0, len(bins) - 2) + ["close_up"]

    head_desc = ff_desc.strip() or visual_desc.strip()
    tail_desc = lf_desc.strip() or visual_desc.strip()
    mid_desc = visual_desc.strip() or head_desc or tail_desc

    out: List[Dict[str, Any]] = []
    for idx, (s, e) in enumerate(bins):
        desc = mid_desc
        if idx == 0:
            desc = head_desc or mid_desc
        elif idx == len(bins) - 1:
            desc = tail_desc or mid_desc
        out.append(
            {
                "start_s": s,
                "end_s": e,
                "transition": "hard_cut" if idx > 0 else "fade_in",
                "shot_type": types[min(idx, len(types) - 1)],
                "camera_movement": "static" if duration == 5.0 else ("dolly_in" if idx == 0 else "static"),
                "desc": desc[:160],
                "visual_desc": (visual_desc or desc)[:120],
            }
        )
    return out


def _ensure_video_subshots_for_storyboard(storyboard: Any) -> None:
    if not isinstance(storyboard, list):
        return
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        duration = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=15.0)
        item["duration_s"] = float(duration)
        subshots = _normalize_video_subshots(item.get("subshots"), duration_s=float(duration))
        if not subshots:
            subshots = _fallback_video_subshots(
                duration_s=float(duration),
                ff_desc=str(item.get("ff_desc") or ""),
                lf_desc=str(item.get("lf_desc") or ""),
                visual_desc=str(item.get("visual_desc") or item.get("desc") or ""),
            )
        item["subshots"] = subshots


def _clean_text_chars(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fa5]", "", str(text or ""))


def _scene_key_and_beat_text(text: str) -> Tuple[str, str]:
    """
    从形如“场 1 | 外景 | 地点 | 日：节拍内容”的行里提取 scene_key 与 beat_text。
    """
    s = str(text or "").strip()
    if not s:
        return ("", "")
    for sep in ("：", ":"):
        if sep not in s:
            continue
        head, tail = s.split(sep, 1)
        head = head.strip()
        tail = tail.strip()
        # 含 "|" 的一般是 scene header；限制长度避免把普通对白当 header
        if head and "|" in head and len(head) <= 96 and tail:
            return (head, tail)
        break
    return ("", s)


def _allocate_integer_durations(*, total_s: int, weights: List[float], min_s: int, max_s: int) -> List[int]:
    n = len(weights)
    if n <= 0:
        return []
    total = int(max(1, int(total_s)))
    min_s = int(max(0, int(min_s)))
    max_s = int(max(min_s, int(max_s)))

    # 初分配：按权重比例取整
    wsum = sum(float(w) for w in weights) or 1.0
    durs = [int(round(float(total) * float(w) / wsum)) for w in weights]

    # 夹紧到边界
    durs = [max(min_s, min(max_s, int(d))) for d in durs]

    # 修正总和
    diff = int(total) - int(sum(durs))
    guard = 0
    while diff != 0 and guard < 256:
        guard += 1
        if diff > 0:
            # 给“还没到上限且权重高”的段加 1 秒
            candidates = [(i, weights[i], max_s - durs[i]) for i in range(n) if durs[i] < max_s]
            if not candidates:
                break
            i = max(candidates, key=lambda t: (t[2], t[1]))[0]
            durs[i] += 1
            diff -= 1
        else:
            # 从“高于下限且权重低”的段减 1 秒
            candidates = [(i, weights[i], durs[i] - min_s) for i in range(n) if durs[i] > min_s]
            if not candidates:
                break
            i = min(candidates, key=lambda t: (t[2], t[1]))[0]
            durs[i] -= 1
            diff += 1
    return durs
