"""派生执行事实分阶段冻结服务（GUIDE R9/P0-4，R10/P1-2，验收 37/51）。

full 运行按阶段冻结 ``derived_execution_facts`` 子项（append-only）：
- ``generated_script_facts``（+ ``generated_script_facts_hash``）：剧本生成完成后
- ``voice_resolution``（+ ``voice_resolution_hash``）：voice_binding 完成后
- ``scene_topology``（+ ``scene_topology_hash``）：scene_planning 完成后

合同：
- 冻结过的子项不可覆盖（append-only，重复冻结同 stage 拒绝并返回已冻结）；
- 恢复从最后一个完整阶段的下一阶段继续（不重跑已冻结阶段的非确定性剧本生成、
  不读实时值）；
- 派生事实不参与 input_signature，由各子项 hash 单独校验并记录 result_render_detail；
- 历史缺全部子项的 full 运行按无冻结处理（回退既有恢复行为）。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 阶段顺序（冻结推进顺序；恢复 = 最后冻结子项的下一阶段）
DERIVED_FACT_STAGES = ("generated_script_facts", "voice_resolution", "scene_topology")

# 阶段 → 后续执行阶段（恢复起点语义）
RESUME_AFTER_STAGE = {
    "generated_script_facts": "voice_binding",
    "voice_resolution": "scene_planning",
    "scene_topology": "scene_rendering",
}

_FACT_KEY_BY_STAGE = {
    "generated_script_facts": "generated_script_facts_hash",
    "voice_resolution": "voice_resolution_hash",
    "scene_topology": "scene_topology_hash",
}


def _fact_hash(fact: Any) -> str:
    """子项确定性 hash（JSON 归一化）。"""
    import json

    try:
        canonical = json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        canonical = str(fact)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freeze_derived_fact(
    checkpoint_patch: Dict[str, Any],
    *,
    stage: str,
    fact_payload: Any,
) -> Dict[str, Any]:
    """冻结一个阶段子项到 checkpoint_patch.derived_execution_facts。

    append-only：该 stage 已冻结时拒绝覆盖，返回 ``{"frozen": False,
    "reason": "already_frozen"}``。
    返回 ``{"frozen": bool, "reason": str, "fact_hash": str}``。
    """
    if stage not in DERIVED_FACT_STAGES:
        return {"frozen": False, "reason": f"unknown_stage:{stage}"}

    facts = checkpoint_patch.setdefault("derived_execution_facts", {})
    if not isinstance(facts, dict):
        facts = {}
        checkpoint_patch["derived_execution_facts"] = facts
    if stage in facts:
        return {"frozen": False, "reason": "already_frozen"}

    fact_hash = _fact_hash(fact_payload)
    facts[stage] = {
        "value": fact_payload,
        "hash": fact_hash,
    }
    # 顶层镜像 hash 键（与 checkpoint 既有字段风格一致，供独立校验）
    checkpoint_patch[_FACT_KEY_BY_STAGE[stage]] = fact_hash
    return {"frozen": True, "reason": "frozen", "fact_hash": fact_hash}


def resolve_resume_stage(checkpoint: Optional[Dict[str, Any]]) -> Optional[str]:
    """从 checkpoint 的 derived_execution_facts 确定恢复阶段。

    返回最后一个完整冻结子项的下一执行阶段（voice_binding/scene_planning/
    scene_rendering）；无冻结返回 None（回退既有恢复行为）。
    """
    if not isinstance(checkpoint, dict):
        return None
    facts = checkpoint.get("derived_execution_facts")
    if not isinstance(facts, dict):
        return None

    last_frozen: Optional[str] = None
    for stage in DERIVED_FACT_STAGES:
        entry = facts.get(stage)
        if isinstance(entry, dict) and "hash" in entry:
            last_frozen = stage
        else:
            break  # 顺序推进：中间缺失视为未冻结（不跳过）
    if last_frozen is None:
        return None
    return RESUME_AFTER_STAGE.get(last_frozen)


def verify_derived_facts(checkpoint: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """各子项 hash 独立校验（验收 37：hash 单独校验）。

    返回 ``{"valid": bool, "checked": int, "mismatch": list}``。
    """
    if not isinstance(checkpoint, dict):
        return {"valid": True, "checked": 0, "mismatch": []}
    facts = checkpoint.get("derived_execution_facts")
    if not isinstance(facts, dict):
        return {"valid": True, "checked": 0, "mismatch": []}

    checked = 0
    mismatch: list = []
    for stage in DERIVED_FACT_STAGES:
        entry = facts.get(stage)
        if not isinstance(entry, dict) or "value" not in entry or "hash" not in entry:
            continue
        checked += 1
        expected = entry.get("hash")
        actual = _fact_hash(entry.get("value"))
        if expected != actual:
            mismatch.append(stage)
    return {"valid": not mismatch, "checked": checked, "mismatch": mismatch}


def summarize_frozen_stages(checkpoint: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """冻结子项摘要（供 result_render_detail 审计记录）。"""
    if not isinstance(checkpoint, dict):
        return {"frozen_stages": [], "resume_stage": None}
    facts = checkpoint.get("derived_execution_facts")
    frozen = [
        stage
        for stage in DERIVED_FACT_STAGES
        if isinstance(facts, dict)
        and isinstance(facts.get(stage), dict)
        and "hash" in facts.get(stage)
    ]
    return {
        "frozen_stages": frozen,
        "resume_stage": resolve_resume_stage(checkpoint),
    }


__all__ = [
    "DERIVED_FACT_STAGES",
    "RESUME_AFTER_STAGE",
    "freeze_derived_fact",
    "resolve_resume_stage",
    "summarize_frozen_stages",
    "verify_derived_facts",
]
