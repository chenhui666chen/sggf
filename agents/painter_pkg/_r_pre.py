# -*- coding: utf-8 -*-
"""R-pre 候选择优门位（Phase 2.4 · 10.6 candidate_selection_gate 的图片层落地）。

高价值 beat（情绪爆发族 / 信息揭示族 / 冲突动作族，即 R-pre 标记的镜头）强制双候选，
VLM 按帧 prompt（含 Contract 字段）预评择优后再进视频生成——把择优前移到最贵环节之前。
预算闸门：候选 ≤2/镜；低分候选归档由 keep_candidates/telemetry 承接（学习回路燃料）。
"""
from __future__ import annotations

from typing import Any, Dict

R_PRE_FAMILIES = {"情绪爆发族", "信息揭示族", "冲突动作族"}
R_PRE_MAX_CANDIDATES = 2


def is_r_pre_eligible(item: Dict[str, Any]) -> bool:
    """镜头是否 R-pre 高价值：Contract 引擎显式标记，或 beat 族兜底判定。"""
    if not isinstance(item, dict):
        return False
    if item.get("r_pre_eligible") is True:
        return True
    return str(item.get("family") or "") in R_PRE_FAMILIES


def r_pre_candidate_count(item: Dict[str, Any], base_count: int, *, enabled: bool = True) -> int:
    """R-pre 门位：高价值镜头候选数抬到 2（预算上限），普通镜头沿用基础配置。"""
    base = max(1, int(base_count or 1))
    if not enabled:
        return base
    if is_r_pre_eligible(item):
        return min(R_PRE_MAX_CANDIDATES, max(base, 2))
    return base


def r_pre_meta(item: Dict[str, Any], shot_count: int, base_count: int) -> Dict[str, Any]:
    """门位元数据（落进帧 meta / 调用审计的输入）。"""
    return {
        "eligible": is_r_pre_eligible(item),
        "candidates": int(shot_count),
        "base_candidates": int(base_count),
        "bumped": int(shot_count) > int(base_count),
        "families": sorted(R_PRE_FAMILIES),
    }
