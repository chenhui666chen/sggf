# -*- coding: utf-8 -*-
"""分镜引擎知识加载（Phase 2.3）：从 config/director_knowledge/ 载入 Contract 引擎消费的知识。

按需求拉动原则只预载分镜阶段固定集合：
  - beat_family_routing（T2 路由：七族 → dispatch DC ids）
  - DC-035（运镜八映射）/ DC-036（灯光八映射）/ DC-037（关键帧来源分叉）完整案例
  - cinematography 域：shot_size_system / cinematography_decision_library /
    technique_interference_check / camera_lighting_prompt_lexicon / internal_motion_priority
  - production 域：model_tiered_duration / sparse_keyframe_cot / candidate_selection_before_commit
  - character 域：closed_action_lexicon（动作词典，state 链拆词用）
  - cases/cf_triggers.json（T3 预检 16 条触发器）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "config" / "director_knowledge"

_CACHE: Dict[str, Any] = {}


def _load_json(rel: str) -> Dict[str, Any]:
    path = KNOWLEDGE_DIR / rel
    if not path.exists():
        raise RuntimeError(
            f"分镜引擎知识缺失：{path} 不存在。"
            "请先运行：python scripts/split_director_knowledge.py"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _unit(domain_file: str, unit_id: str) -> Dict[str, Any]:
    data = _load_json(f"domains/{domain_file}.json")
    unit = data.get("units", {}).get(unit_id)
    if not isinstance(unit, dict):
        raise RuntimeError(f"知识单元 {unit_id} 不在 domains/{domain_file}.json 中")
    return unit


def load_storyboard_knowledge() -> Dict[str, Any]:
    """分镜阶段知识集合（进程级缓存）。"""
    if "knowledge" in _CACHE:
        return _CACHE["knowledge"]

    routing = _load_json("cases/beat_family_routing.json")
    families = [
        {
            "family": fam.get("family", ""),
            "keywords": [str(k) for k in fam.get("keywords", [])],
            "dispatch": [str(d) for d in fam.get("dispatch", [])],
        }
        for fam in routing.get("beat_families", [])
        if isinstance(fam, dict) and fam.get("family")
    ]

    cases = _load_json("cases/director_cases.json")
    dc_by_id = {c["id"]: c for c in cases.get("cases", []) if isinstance(c, dict) and c.get("id")}

    triggers = _load_json("cases/cf_triggers.json").get("triggers", [])

    knowledge = {
        "beat_families": families,
        "beat_family_names": [f["family"] for f in families],
        "dc_by_id": dc_by_id,
        "cf_triggers": triggers,
        "shot_size_system": _unit("cinematography", "shot_size_system"),
        "decision_library": _unit("cinematography", "cinematography_decision_library"),
        "interference": _unit("cinematography", "technique_interference_check"),
        "prompt_lexicon": _unit("cinematography", "camera_lighting_prompt_lexicon"),
        "internal_motion": _unit("cinematography", "internal_motion_priority"),
        # 图片层补强（2026-10-07）：帧编译消费的摄影域单元
        "lens_perspective": _unit("cinematography", "lens_camera_distance_perspective"),
        "composition_attention": _unit("cinematography", "composition_attention"),
        "subject_separation": _unit("cinematography", "subject_separation"),
        "color_grade": _unit("cinematography", "color_grade_thinking"),
        "texture_boost": _unit("cinematography", "texture_boost_techniques"),
        "tiered_duration": _unit("production", "model_tiered_duration"),
        "sparse_keyframe": _unit("production", "sparse_keyframe_cot"),
        "r_pre": _unit("production", "candidate_selection_before_commit"),
        # 图片层补强（2026-10-07）：I2V 帧质量 + 模型方言
        "i2v_frame_quality": _unit("production", "i2v_frame_quality_protocol"),
        "model_dialects": _unit("image_generation", "model_prompt_dialects"),
    }
    _CACHE["knowledge"] = knowledge
    return knowledge


def dispatch_dc_ids(family: str, knowledge: Dict[str, Any]) -> List[str]:
    """T2：beat 族 → dispatch DC 清单（未登记族返回空，走基础方案）。"""
    for f in knowledge.get("beat_families", []):
        if f["family"] == family:
            return list(f["dispatch"])
    return []
