"""Seed 场景 checkpoint schema registry 与合同版本定义（指导文档 §12.2）。

每类 checkpoint 在 registry 中登记 schema 版本、签名合同版本与必备字段；
缺字段不得静默当作命中。新增 schema 版本必须 append-only 登记并通过
迁移器衔接，禁止原地覆盖历史版本定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Tuple

SEED_SCENE_CHECKPOINT_TYPE = "seed_scene_checkpoint"
SEED_SCENE_CHECKPOINT_SCHEMA_V1 = 1
SEED_SCENE_CHECKPOINT_SCHEMA_V2 = 2
CURRENT_SEED_SCENE_CHECKPOINT_SCHEMA_VERSION = SEED_SCENE_CHECKPOINT_SCHEMA_V2

# canonical_hash 合同身份（§12.2 Hash API 职责分离）。
SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_NAME = "seed_scene_checkpoint_signature"
SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION = "1.0.0"

# v1 生成侧签名字段：迁移与复用验证都不得绕过这些字段。
_V1_SIGNATURE_FIELDS = (
    "schema_version",
    "renderer_version",
    "model",
    "audio_config",
    "scene_id",
    "prompt_hash",
    "quality_policy_hash",
    "reference_hashes",
    "status",
    "attempts",
)

# v2 在 v1 基础上要求显式元数据（指导文档 §12.2：每类 checkpoint 显式保存
# checkpoint_type、checkpoint_schema_version、signature_contract_version、
# created_at、producer_version）。created_at 由生成侧写入；迁移版本以
# migrated_at 承载时间审计，故 registry 不强制 created_at。
_V2_METADATA_FIELDS = (
    "checkpoint_type",
    "signature_contract_version",
    "producer_version",
)


@dataclass(frozen=True)
class CheckpointSchemaSpec:
    schema_version: int
    checkpoint_type: str
    contract_version: str
    required_fields: Tuple[str, ...]


_SCHEMA_REGISTRY = {
    SEED_SCENE_CHECKPOINT_SCHEMA_V1: CheckpointSchemaSpec(
        schema_version=SEED_SCENE_CHECKPOINT_SCHEMA_V1,
        checkpoint_type=SEED_SCENE_CHECKPOINT_TYPE,
        contract_version=SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION,
        required_fields=_V1_SIGNATURE_FIELDS,
    ),
    SEED_SCENE_CHECKPOINT_SCHEMA_V2: CheckpointSchemaSpec(
        schema_version=SEED_SCENE_CHECKPOINT_SCHEMA_V2,
        checkpoint_type=SEED_SCENE_CHECKPOINT_TYPE,
        contract_version=SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION,
        required_fields=_V1_SIGNATURE_FIELDS + _V2_METADATA_FIELDS,
    ),
}


def get_checkpoint_schema(schema_version: Any) -> CheckpointSchemaSpec | None:
    """按 schema 版本取登记规格；未登记版本返回 None（不得静默兼容）。"""
    try:
        version = int(schema_version)
    except (TypeError, ValueError, OverflowError):
        return None
    return _SCHEMA_REGISTRY.get(version)


def validate_checkpoint_identity(
    checkpoint: Mapping[str, Any] | None,
) -> tuple[bool, tuple[str, ...]]:
    """校验 checkpoint 结构身份，返回 (是否通过, 问题列表)。

    缺字段必须显式报告，不得静默当作命中。
    """
    if not isinstance(checkpoint, Mapping):
        return False, ("checkpoint_not_a_mapping",)
    schema = get_checkpoint_schema(checkpoint.get("schema_version"))
    if schema is None:
        return False, (f"unknown_schema_version:{checkpoint.get('schema_version')!r}",)
    problems = tuple(
        f"missing_field:{field}"
        for field in schema.required_fields
        if field not in checkpoint or checkpoint.get(field) in (None, "")
    )
    return (not problems), problems


__all__ = [
    "CURRENT_SEED_SCENE_CHECKPOINT_SCHEMA_VERSION",
    "SEED_SCENE_CHECKPOINT_SCHEMA_V1",
    "SEED_SCENE_CHECKPOINT_SCHEMA_V2",
    "SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_NAME",
    "SEED_SCENE_CHECKPOINT_SIGNATURE_CONTRACT_VERSION",
    "SEED_SCENE_CHECKPOINT_TYPE",
    "CheckpointSchemaSpec",
    "get_checkpoint_schema",
    "validate_checkpoint_identity",
]
