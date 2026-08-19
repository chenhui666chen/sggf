"""SeedSceneDirectorPolicy：服务端版本化预算策略（指导文档 §4.3）。

唯一配置所有权在服务端；普通用户不能提高预算，项目只能请求更低预算，
有效预算取两者最小值。全部合同字段进入策略指纹（policy hash/version
进入 DirectorInputSignature）。首期默认值为保守标定，真实调用标定后可
调整，但调整必须提升 version 并使既有导演 checkpoint 失效。
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Dict, Tuple

from ..hashing import canonical_hash

DIRECTOR_POLICY_CONTRACT_NAME = "seed_scene_director_policy"

# 项目预算可覆盖的字段（只能降低，不能提高）。
_BUDGET_LIMIT_FIELDS = (
    "max_calls_per_chapter",
    "max_tokens_per_chapter",
    "max_cost_per_chapter",
    "max_cost_per_job",
)


@dataclass(frozen=True)
class SeedSceneDirectorPolicy:
    timeout_seconds: float = 90.0
    max_attempts_per_batch: int = 2  # 首次调用 + 最多一次纠错重试
    max_calls_per_chapter: int = 6
    max_tokens_per_chapter: int = 200_000
    max_cost_per_chapter: float = 2.0
    max_cost_per_job: float = 10.0
    version: str = "1.0.0"
    allow_inferred_vocalizations: bool = False
    allowed_inferred_vocalization_types: Tuple[str, ...] = ()
    inferred_vocalization_policy_version: str = "1.0.0"

    def contract_fields(self) -> Dict[str, Any]:
        """返回全部合同字段的构造参数（用于派生新版本策略）。"""
        return {item.name: getattr(self, item.name) for item in fields(self)}

    def fingerprint(self) -> str:
        """策略指纹：任一合同字段或版本变化即变化（进入 DirectorInputSignature）。"""
        payload = {
            name: getattr(self, name)
            for name in (
                "timeout_seconds",
                "max_attempts_per_batch",
                "max_calls_per_chapter",
                "max_tokens_per_chapter",
                "max_cost_per_chapter",
                "max_cost_per_job",
                "allow_inferred_vocalizations",
                "allowed_inferred_vocalization_types",
                "inferred_vocalization_policy_version",
            )
        }
        return canonical_hash(
            payload,
            contract_name=DIRECTOR_POLICY_CONTRACT_NAME,
            contract_version=self.version,
        )


DEFAULT_SEED_SCENE_DIRECTOR_POLICY = SeedSceneDirectorPolicy()


def resolve_effective_policy(
    server_policy: SeedSceneDirectorPolicy, **project_limits: Any
) -> SeedSceneDirectorPolicy:
    """合并项目预算请求：只允许更低，有效预算取最小值（§4.3）。"""
    updates: Dict[str, Any] = {}
    for name in _BUDGET_LIMIT_FIELDS:
        if name not in project_limits or project_limits[name] is None:
            continue
        requested = project_limits[name]
        current = getattr(server_policy, name)
        if requested < current:
            updates[name] = requested
    if not updates:
        return server_policy
    return replace(server_policy, **updates)


__all__ = [
    "DEFAULT_SEED_SCENE_DIRECTOR_POLICY",
    "DIRECTOR_POLICY_CONTRACT_NAME",
    "SeedSceneDirectorPolicy",
    "resolve_effective_policy",
]
