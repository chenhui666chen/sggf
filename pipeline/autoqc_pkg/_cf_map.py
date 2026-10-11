# -*- coding: utf-8 -*-
"""CF 库 L1 直索映射（Phase 2.5）：autoqc failure_type → CF 案例 + repair_model。

L1 协议：失败码/失败类型直接命中 CF 案例（repair_model 优先于 repair——双视角修复）；
映射不到的走 L3 语义兜底（运行时由 semantic 检索），此处给 candidate_cf 空标记。
CF 库从 config/director_knowledge/cases/failure_cases.json（SSOT 派生）惰性加载。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CF_LIBRARY_PATH = REPO_ROOT / "config" / "director_knowledge" / "cases" / "failure_cases.json"

# autoqc 13 类 failure_type → CF 映射 + 默认 R 级（R 级为路由兜底，最终以 _routing 决策为准）
FAILURE_TO_CF: Dict[str, Dict[str, Any]] = {
    # ---- 基建类（无对应 CF，走 R1 元数据/资产层修复）----
    "missing_head_frame": {"cf_ids": [], "default_r": "R1", "note": "基建：首帧资产缺失"},
    "missing_tail_frame": {"cf_ids": [], "default_r": "R1", "note": "基建：尾帧资产缺失"},
    "ratio_mismatch": {"cf_ids": [], "default_r": "R1", "note": "基建：画幅规格不一致"},
    "missing_subject_pos": {"cf_ids": [], "default_r": "R1", "note": "基建：主体位置缺失"},
    "video_engine_not_i2v": {"cf_ids": [], "default_r": "R1", "note": "基建：引擎路由不符"},
    "i2v_fallback": {"cf_ids": [], "default_r": "R0", "note": "降级容忍：接受并留痕（R0+元数据）"},
    "missing_video_clips": {"cf_ids": [], "default_r": "R4", "note": "基建：视频片段缺失→整镜重生成"},
    # ---- 电影语言类（L1 直索 CF）----
    "shot_continuity_break": {"cf_ids": ["CF-109"], "default_r": "R2",
                              "note": "镜内连续性断裂→硬切无落点（动接动/落点三规则）"},
    "cross_shot_continuity_break": {"cf_ids": ["CF-110", "CF-021"], "default_r": "R2",
                                    "note": "跨镜断裂→转场缺失/身份漂移"},
    "camera_continuity_break": {"cf_ids": ["CF-034"], "default_r": "R2",
                                "note": "机位/景别连续性→景别随机变化"},
    "state_continuity_mismatch": {"cf_ids": ["CF-030", "CF-028"], "default_r": "R2",
                                  "note": "状态断裂→动作物理链缺失/道具实体绑定丢失"},
    "semantic_mismatch": {"cf_ids": ["CF-014"], "default_r": "R3", "l3_fallback": True,
                          "note": "画面与意图不符→候选词命中不足，L3 语义兜底扩查"},
    "video_clip_quality_below_threshold": {"cf_ids": ["CF-015", "CF-029"], "default_r": "R3",
                                           "note": "片段质量→动作无重量/手物交互失败（模型原理类）"},
    "overall_score_below_threshold": {"cf_ids": [], "default_r": "R3", "l3_fallback": True,
                                      "note": "综合分不足→多因叠加，L3 语义兜底"},
}

_CF_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _load_cf_library() -> Dict[str, Dict[str, Any]]:
    global _CF_CACHE
    if _CF_CACHE is not None:
        return _CF_CACHE
    if not CF_LIBRARY_PATH.exists():
        _CF_CACHE = {}
        return _CF_CACHE
    with open(CF_LIBRARY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    _CF_CACHE = {str(c.get("id")): c for c in data.get("cases", []) if isinstance(c, dict) and c.get("id")}
    return _CF_CACHE


def resolve_cf_hits(failure_types: List[str], *, max_per_cf: int = 3) -> List[Dict[str, Any]]:
    """L1 直索：failure_type → CF 案例摘要（含 repair_model，双视角修复优先）。"""
    library = _load_cf_library()
    hits: List[Dict[str, Any]] = []
    seen: set = set()
    for ft in failure_types or []:
        spec = FAILURE_TO_CF.get(str(ft or "").strip())
        if not spec:
            continue
        for cf_id in spec.get("cf_ids", [])[:max_per_cf]:
            if cf_id in seen:
                continue
            case = library.get(cf_id)
            if not case:
                continue
            seen.add(cf_id)
            hits.append({
                "failure_type": str(ft),
                "cf_id": cf_id,
                "title": str(case.get("title") or ""),
                # repair_model（模型原理视角）优先于 repair（导演视角）——双视角修复纪律
                "repair_model": str(case.get("repair_model") or case.get("repair") or "")[:400],
            })
    return hits


def l1_direct_lookup(cf_id: str) -> Optional[Dict[str, Any]]:
    """L1 失败码直索（修复路由/审计按 CF 编号取完整案例）。"""
    return _load_cf_library().get(str(cf_id or "").strip())


def mapping_report() -> Dict[str, Any]:
    """映射表健康报告（覆盖率统计，调用审计用）。"""
    library = _load_cf_library()
    mapped = sum(1 for spec in FAILURE_TO_CF.values() if spec.get("cf_ids"))
    resolvable = sum(
        1 for spec in FAILURE_TO_CF.values()
        if any(cid in library for cid in spec.get("cf_ids", []))
    )
    return {
        "failure_types_total": len(FAILURE_TO_CF),
        "types_with_cf_mapping": mapped,
        "types_resolvable_in_library": resolvable,
        "cf_library_size": len(library),
        "l3_fallback_types": sorted(k for k, v in FAILURE_TO_CF.items() if v.get("l3_fallback")),
    }
