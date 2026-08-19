"""声音绑定 hash 分离（指导文档 §7.8/§12.2）。

binding_decision_hash 只包含影响 Seed 生成结果的决策字段
（speaker/slot_index/reference_content_hash/description/decision/
required_stability），作为 Seed 生成缓存键的一部分；
binding_audit_hash 包含审计字段（policy_version/registry_version/
priority_score/reason_code/identity_source），其变化只影响审计记录，
不触发 Seed 重新生成。二进制内容一律经 content_digest，不进入
canonical_hash。
"""

from __future__ import annotations

from typing import Mapping

from ..hashing import canonical_hash
from .voice_binding_planner import SceneVoiceBinding, SceneVoiceBindingPlan

_DECISION_CONTRACT = "seed_scene_voice_binding_decision"
_DECISION_CONTRACT_VERSION = "1.0.0"
_AUDIT_CONTRACT = "seed_scene_voice_binding_audit"
_AUDIT_CONTRACT_VERSION = "1.0.0"


def _sort_key(binding: SceneVoiceBinding):
    return (
        binding.slot_index is None,
        binding.slot_index if binding.slot_index is not None else 0,
        binding.speaker,
    )


def binding_decision_hash(
    plan: SceneVoiceBindingPlan, reference_content_hashes: Mapping[str, str]
) -> str:
    """决策 hash：只有改变 Prompt/音色映射的字段才参与。

    reference 二进制内容以预先计算的 content digest 传入
    （reference_content_hashes: speaker -> digest），不进入 canonical 形式。
    """
    bindings = []
    for binding in sorted(plan.bindings, key=_sort_key):
        bindings.append(
            {
                "speaker": binding.speaker,
                "slot_index": binding.slot_index,
                "decision": binding.decision,
                "description": binding.description,
                "required_stability": binding.required_stability,
                "reference_content_hash": reference_content_hashes.get(binding.speaker, ""),
            }
        )
    return canonical_hash(
        {"scene_id": plan.scene_id, "bindings": bindings},
        contract_name=_DECISION_CONTRACT,
        contract_version=_DECISION_CONTRACT_VERSION,
    )


def binding_audit_hash(plan: SceneVoiceBindingPlan) -> str:
    """审计 hash：决策依据与版本信息，仅供审计与回放。"""
    bindings = []
    for binding in sorted(plan.bindings, key=_sort_key):
        bindings.append(
            {
                "speaker": binding.speaker,
                "slot_index": binding.slot_index,
                "decision": binding.decision,
                "reason_code": binding.reason_code,
                "priority_score": binding.priority_score,
                "identity_source": binding.identity_source,
                "required_stability": binding.required_stability,
            }
        )
    return canonical_hash(
        {
            "scene_id": plan.scene_id,
            "registry_version": plan.registry_version,
            "policy_version": plan.policy_version,
            "reference_count": plan.reference_count,
            "bindings": bindings,
        },
        contract_name=_AUDIT_CONTRACT,
        contract_version=_AUDIT_CONTRACT_VERSION,
    )


__all__ = ["binding_audit_hash", "binding_decision_hash"]
