"""Seed 场景 checkpoint append-only 迁移 runner（指导文档 §12.2 历史恢复原则）。

原则：

- 原 checkpoint 保持只读，不做原地覆盖；迁移产出引用旧 checkpoint 的新版本。
- attempt ledger、provider request ID、计费记录只引用，不复制成新的消费事件。
- 迁移必须幂等：相同旧 checkpoint 身份 + migration version 只产生一个确定性结果。
- 迁移失败不破坏旧 checkpoint，进入明确的 ``legacy_checkpoint_incompatible``。
- 已有音频 artifact 完整时，不因 schema 升级重烧 Seed；迁移不重置任何预算。
- migration_input_hash 使用统一 ``canonical_hash`` 基础设施的版本化合同。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from app.services.audiobook.hashing import canonical_hash

from .checkpoint_contracts import (
    SEED_SCENE_CHECKPOINT_SCHEMA_V1,
    SEED_SCENE_CHECKPOINT_SCHEMA_V2,
    SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_NAME,
    SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION,
    SEED_SCENE_CHECKPOINT_TYPE,
    validate_checkpoint_identity,
)

# 迁移合同版本（实施基线约定：编码时固定为版本化合同）。
MIGRATION_CONTRACT_NAME = "seed_scene_checkpoint_migration"
MIGRATION_CONTRACT_VERSION = "1.0.0"
SEED_SCENE_V1_TO_V2_MIGRATION_VERSION = "seed-scene-checkpoint-v1-to-v2@1.0.0"

MIGRATION_STATUS_MIGRATED = "migrated"
MIGRATION_STATUS_ALREADY_MIGRATED = "already_migrated"
MIGRATION_STATUS_INCOMPATIBLE = "legacy_checkpoint_incompatible"


@dataclass(frozen=True)
class CheckpointMigrationResult:
    status: str
    checkpoint: Optional[dict]
    migration_input_hash: Optional[str]
    reasons: Tuple[str, ...]


def compute_checkpoint_identity(checkpoint: Mapping[str, Any]) -> str:
    """旧 checkpoint 的结构化语义身份（版本化 canonical_hash）。"""
    return canonical_hash(
        dict(checkpoint),
        contract_name=SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_NAME,
        contract_version=SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION,
    )


def compute_migration_input_hash(
    checkpoint: Mapping[str, Any], *, migration_version: str
) -> str:
    """migration_input_hash 版本化合同。

    输入至少包含：旧 checkpoint 身份、旧 schema/version、目标 schema/version、
    migration version、迁移所依赖的确定性输入摘要。
    """
    payload = {
        "checkpoint_type": SEED_SCENE_CHECKPOINT_TYPE,
        "old_checkpoint_identity": compute_checkpoint_identity(checkpoint),
        "source_schema_version": SEED_SCENE_CHECKPOINT_SCHEMA_V1,
        "target_schema_version": SEED_SCENE_CHECKPOINT_SCHEMA_V2,
        "migration_version": migration_version,
        "signature_contract_version": SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION,
    }
    return canonical_hash(
        payload,
        contract_name=MIGRATION_CONTRACT_NAME,
        contract_version=MIGRATION_CONTRACT_VERSION,
    )


def migrate_seed_scene_checkpoint(
    checkpoint: Mapping[str, Any] | None, *, now_iso: str
) -> CheckpointMigrationResult:
    """把历史 v1 场景 checkpoint 确定性补算为 v2（append-only，幂等）。

    成功时返回新版本 dict：旧签名字段逐项继承、不重算；新增迁移审计字段。
    无法证明兼容时返回 legacy_checkpoint_incompatible，旧 checkpoint 不受影响。
    """
    if not isinstance(checkpoint, Mapping):
        return CheckpointMigrationResult(
            status=MIGRATION_STATUS_INCOMPATIBLE,
            checkpoint=None,
            migration_input_hash=None,
            reasons=("checkpoint_not_a_mapping",),
        )

    try:
        schema_version = int(checkpoint.get("schema_version"))
    except (TypeError, ValueError, OverflowError):
        return CheckpointMigrationResult(
            status=MIGRATION_STATUS_INCOMPATIBLE,
            checkpoint=None,
            migration_input_hash=None,
            reasons=(
                f"unknown_schema_version:{checkpoint.get('schema_version')!r}",
            ),
        )

    if schema_version == SEED_SCENE_CHECKPOINT_SCHEMA_V2:
        # 已是当前版本（含历史迁移产物）：幂等复用，不叠加迁移历史。
        return CheckpointMigrationResult(
            status=MIGRATION_STATUS_ALREADY_MIGRATED,
            checkpoint=dict(checkpoint),
            migration_input_hash=_existing_migration_hash(checkpoint),
            reasons=(),
        )

    if schema_version != SEED_SCENE_CHECKPOINT_SCHEMA_V1:
        return CheckpointMigrationResult(
            status=MIGRATION_STATUS_INCOMPATIBLE,
            checkpoint=None,
            migration_input_hash=None,
            reasons=(f"unknown_schema_version:{schema_version}",),
        )

    valid, problems = validate_checkpoint_identity(checkpoint)
    if not valid:
        # 缺字段不得静默当作命中。
        return CheckpointMigrationResult(
            status=MIGRATION_STATUS_INCOMPATIBLE,
            checkpoint=None,
            migration_input_hash=None,
            reasons=problems,
        )

    try:
        identity = compute_checkpoint_identity(checkpoint)
        input_hash = compute_migration_input_hash(
            checkpoint,
            migration_version=SEED_SCENE_V1_TO_V2_MIGRATION_VERSION,
        )
    except TypeError as exc:
        return CheckpointMigrationResult(
            status=MIGRATION_STATUS_INCOMPATIBLE,
            checkpoint=None,
            migration_input_hash=None,
            reasons=(f"unhashable_checkpoint:{exc}",),
        )

    migrated = dict(checkpoint)
    migrated.update(
        {
            "schema_version": SEED_SCENE_CHECKPOINT_SCHEMA_V2,
            "checkpoint_type": SEED_SCENE_CHECKPOINT_TYPE,
            "signature_contract_version": (
                SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION
            ),
            "producer_version": str(checkpoint.get("renderer_version") or ""),
            "original_schema_version": SEED_SCENE_CHECKPOINT_SCHEMA_V1,
            "migration_version": SEED_SCENE_V1_TO_V2_MIGRATION_VERSION,
            "migration_input_hash": input_hash,
            "migration_status": MIGRATION_STATUS_MIGRATED,
            "migrated_from_checkpoint_hash": identity,
            "migrated_at": now_iso,
            "migration_history": [
                {
                    "migration_version": SEED_SCENE_V1_TO_V2_MIGRATION_VERSION,
                    "migration_input_hash": input_hash,
                    "migrated_from_checkpoint_hash": identity,
                    "migrated_at": now_iso,
                }
            ],
        }
    )
    return CheckpointMigrationResult(
        status=MIGRATION_STATUS_MIGRATED,
        checkpoint=migrated,
        migration_input_hash=input_hash,
        reasons=(),
    )


def _existing_migration_hash(checkpoint: Mapping[str, Any]) -> Optional[str]:
    value = checkpoint.get("migration_input_hash")
    return str(value) if value else None


__all__ = [
    "MIGRATION_CONTRACT_NAME",
    "MIGRATION_CONTRACT_VERSION",
    "MIGRATION_STATUS_ALREADY_MIGRATED",
    "MIGRATION_STATUS_INCOMPATIBLE",
    "MIGRATION_STATUS_MIGRATED",
    "SEED_SCENE_V1_TO_V2_MIGRATION_VERSION",
    "CheckpointMigrationResult",
    "compute_checkpoint_identity",
    "compute_migration_input_hash",
    "migrate_seed_scene_checkpoint",
]
