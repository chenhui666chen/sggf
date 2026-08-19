"""Omni 期望合同规范化（指导文档 §12.2 omni_expectation_contract_hash）。

规范化输入覆盖 §10.2 完整 Omni 输入合同，缺任一部分即拒绝；规范化与
mapping 字段顺序无关（canonical_hash 按 key 排序），但有顺序语义的
数组（台词顺序、事件时序）保持顺序。

``voice_binding_summary_hash`` 独立保留供审计，但其内容与期望合同从
同一规范化来源生成（binding summary 在两侧都先按 slot/speaker 排序），
避免双重字段语义不一致。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ..hashing import canonical_hash

EXPECTATION_CONTRACT_NAME = "omni_expectation_contract"
BINDING_SUMMARY_CONTRACT_NAME = "omni_voice_binding_summary"
_CONTRACT_VERSION = "1.0.0"

# §10.2/§12.2 完整 Omni 输入合同的必需组成部分。
EXPECTATION_REQUIRED_PARTS: Tuple[str, ...] = (
    "scene_context",
    "speech",
    "vocalizations",
    "sound_events",
    "music_ambient",
    "acoustic_treatment",
    "performance_expectations",
    "timeline_windows",
    "voice_binding_summary",
    "carry_state",
    "target_duration_s",
)


def _sorted_bindings(
    bindings: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """同一规范化来源：binding summary 按 (slot_index, speaker) 确定性排序。"""
    return sorted(
        (dict(binding) for binding in bindings),
        key=lambda item: (
            item.get("slot_index") is None,
            item.get("slot_index"),
            str(item.get("speaker", "")),
        ),
    )


def build_voice_binding_summary(
    bindings: Sequence[Mapping[str, Any]],
) -> str:
    """voice_binding_summary_hash：独立保留供审计的绑定摘要身份。"""
    return canonical_hash(
        {"bindings": _sorted_bindings(bindings)},
        contract_name=BINDING_SUMMARY_CONTRACT_NAME,
        contract_version=_CONTRACT_VERSION,
    )


def omni_expectation_contract_hash(expectation: Mapping[str, Any]) -> str:
    """完整声音场景期望合同 hash（Omni 评审缓存键的组成部分）。"""
    keys = set(expectation)
    missing = [part for part in EXPECTATION_REQUIRED_PARTS if part not in keys]
    if missing:
        raise ValueError(
            f"omni expectation contract is missing parts: {sorted(missing)}"
        )
    unknown = keys - set(EXPECTATION_REQUIRED_PARTS)
    if unknown:
        raise ValueError(
            f"omni expectation contract has untracked parts: {sorted(unknown)}"
        )

    payload: Dict[str, Any] = dict(expectation)
    # 与 build_voice_binding_summary 使用同一规范化来源（确定性排序）。
    payload["voice_binding_summary"] = _sorted_bindings(
        expectation["voice_binding_summary"]
    )
    return canonical_hash(
        payload,
        contract_name=EXPECTATION_CONTRACT_NAME,
        contract_version=_CONTRACT_VERSION,
    )


__all__ = [
    "EXPECTATION_REQUIRED_PARTS",
    "build_voice_binding_summary",
    "omni_expectation_contract_hash",
]
