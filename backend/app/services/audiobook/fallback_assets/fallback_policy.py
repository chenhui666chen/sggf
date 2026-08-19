"""回退资产策略（指导文档阶段 7/§15/§16）。

Seed 主路径不提前生成真实分轨素材；回退时按场景生成并持久化
artifact；legacy fallback 具备独立开关（§15）；所有回退对用户和
账单明确可见，任何回滚不得重新计费已通过且签名兼容的场景。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

from ..hashing import canonical_hash

FALLBACK_POLICY_CONTRACT_NAME = "fallback_asset_policy"


@dataclass(frozen=True)
class FallbackAssetPolicy:
    """版本化回退资产策略；指纹进入回退计划审计。"""

    enabled: bool = True
    policy_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not str(self.policy_version).strip():
            raise ValueError("policy_version must be non-empty")

    @property
    def pre_generates_on_seed_path(self) -> bool:
        """Seed 成功路径不提前产生不必要的分轨素材（§16），恒定语义。"""
        return False

    @property
    def generates_per_scene(self) -> bool:
        """回退素材按场景生成，不整章批量生成（阶段 7），恒定语义。"""
        return True

    @property
    def allows_fallback(self) -> bool:
        """legacy fallback 独立开关（§15）。"""
        return bool(self.enabled)

    @property
    def visible_to_user(self) -> bool:
        """回退状态对用户明确可见（§16），不可隐藏。"""
        return True

    @property
    def visible_in_billing(self) -> bool:
        """回退成本在账单中明确可见（§16），不可隐藏。"""
        return True

    @property
    def allows_rebill_passed_scene(self) -> bool:
        """任何回滚不得重新计费已通过且签名兼容的场景（§15）。"""
        return False

    @classmethod
    def from_mapping(cls, overrides: Mapping[str, Any]) -> FallbackAssetPolicy:
        base = DEFAULT_FALLBACK_ASSET_POLICY
        merged: Dict[str, Any] = {
            "enabled": base.enabled,
            "policy_version": base.policy_version,
        }
        for key, value in overrides.items():
            if key not in merged:
                raise ValueError(f"unknown fallback asset policy field: {key}")
            merged[key] = value
        return cls(**merged)

    def fingerprint(self) -> str:
        return canonical_hash(
            {
                "enabled": bool(self.enabled),
                "policy_version": self.policy_version,
            },
            contract_name=FALLBACK_POLICY_CONTRACT_NAME,
            contract_version=self.policy_version,
        )


DEFAULT_FALLBACK_ASSET_POLICY = FallbackAssetPolicy()


__all__ = [
    "DEFAULT_FALLBACK_ASSET_POLICY",
    "FallbackAssetPolicy",
]
