# -*- coding: utf-8 -*-
"""知识加载：从 config/director_knowledge/（SSOT 派生目录，Phase 2.1 产物）读取剧本引擎所需知识。

只加载剧本阶段消费的知识（需求拉动原则：无触发不检索——这里按阶段预载固定集合）：
  - beat_family_routing：七族 + 关键词（T2 路由的注册表）
  - closed_action_lexicon：闭合动作词典（character 域）
  - script_generator_compatibility：剧本-生成器兼容性（production 域）
  - dialogue_coverage / resonance_design：对白覆盖与共鸣设计（director_reasoning 域）
  - adaptation_resource_protocol：资源复用协议要点（production 域）

目录缺失时抛出带修复指引的异常（Phase 2.1 是硬前置）。
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
            f"剧本引擎知识缺失：{path} 不存在。"
            "请先运行 Phase 2.1 派生脚本：python scripts/split_director_knowledge.py"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _unit(domain_file: str, unit_id: str) -> Dict[str, Any]:
    data = _load_json(f"domains/{domain_file}.json")
    unit = data.get("units", {}).get(unit_id)
    if not isinstance(unit, dict):
        raise RuntimeError(f"知识单元 {unit_id} 不在 domains/{domain_file}.json 中")
    return unit


def _content_lines(unit: Dict[str, Any]) -> List[str]:
    lines = unit.get("content")
    if isinstance(lines, list):
        return [str(x) for x in lines if str(x).strip()]
    return []


def load_script_knowledge() -> Dict[str, Any]:
    """加载剧本引擎知识集合（进程级缓存）。"""
    if "knowledge" in _CACHE:
        return _CACHE["knowledge"]

    routing = _load_json("cases/beat_family_routing.json")
    families = [
        {
            "family": fam.get("family", ""),
            "keywords": [str(k) for k in fam.get("keywords", [])],
        }
        for fam in routing.get("beat_families", [])
        if isinstance(fam, dict) and fam.get("family")
    ]

    lexicon_lines = _content_lines(_unit("character", "closed_action_lexicon"))
    compat_lines = _content_lines(_unit("production", "script_generator_compatibility"))
    dialogue_lines = _content_lines(_unit("director_reasoning", "dialogue_coverage"))
    resonance_lines = _content_lines(_unit("director_reasoning", "resonance_design"))
    reuse_lines = _content_lines(_unit("production", "adaptation_resource_protocol"))

    knowledge = {
        "beat_families": families,
        "beat_family_names": [f["family"] for f in families],
        "action_lexicon_lines": lexicon_lines,
        "compat_rules": compat_lines,
        "dialogue_coverage_rules": dialogue_lines,
        "resonance_rules": resonance_lines,
        "reuse_rules": reuse_lines,
    }
    _CACHE["knowledge"] = knowledge
    return knowledge
