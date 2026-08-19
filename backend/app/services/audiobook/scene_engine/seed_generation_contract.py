"""Seed 生成输入签名与输出校验分离（指导文档 §12.2 Seed artifact checkpoint）。

SeedGenerationInputSignature 是唯一生成缓存键：只签名会改变成品音频或
解析合同的规范化请求参数；API Key、临时 URL、Request ID、超时值、
binding_audit_hash 一律不进入生成缓存键。SeedGenerationOutput 只做输出
校验，其 artifact hash 变化属于输出完整性问题，不是“输入签名变化”。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ..hashing import canonical_hash

SEED_GENERATION_INPUT_CONTRACT_NAME = "seed_generation_input"
SEED_GENERATION_INPUT_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class SeedGenerationInputSignature:
    """Seed 生成输入签名（字段白名单即合同，禁止携带瞬时字段）。"""

    model_id: str
    timeline_mode: str
    prompt_hash: str
    reference_hashes: Tuple[str, ...]
    scene_voice_identity_hash: str
    binding_decision_hash: str
    provider_id: str
    provider_resource_id: str
    provider_request_schema_hash: str
    adapter_contract_version: str
    requested_audio_format: str
    requested_sample_rate: int
    requested_channels: int

    def signature_hash(self) -> str:
        payload = {
            "model_id": self.model_id,
            "timeline_mode": self.timeline_mode,
            "prompt_hash": self.prompt_hash,
            # references 数组位置与 @音频N 映射相关，顺序参与签名。
            "reference_hashes": tuple(self.reference_hashes),
            "scene_voice_identity_hash": self.scene_voice_identity_hash,
            "binding_decision_hash": self.binding_decision_hash,
            "provider_id": self.provider_id,
            "provider_resource_id": self.provider_resource_id,
            "provider_request_schema_hash": self.provider_request_schema_hash,
            "adapter_contract_version": self.adapter_contract_version,
            "requested_audio_format": self.requested_audio_format,
            "requested_sample_rate": self.requested_sample_rate,
            "requested_channels": self.requested_channels,
        }
        return canonical_hash(
            payload,
            contract_name=SEED_GENERATION_INPUT_CONTRACT_NAME,
            contract_version=SEED_GENERATION_INPUT_CONTRACT_VERSION,
        )


@dataclass(frozen=True)
class SeedGenerationOutput:
    """输出校验载体：不进入缓存键，只用于复用前的一致性检查。"""

    audio_artifact_hash: str
    provider_request_id: str
    actual_audio_format: str
    actual_sample_rate: int
    actual_channels: int
    duration_s: float
    provider_metadata_hash: str


__all__ = [
    "SEED_GENERATION_INPUT_CONTRACT_NAME",
    "SEED_GENERATION_INPUT_CONTRACT_VERSION",
    "SeedGenerationInputSignature",
    "SeedGenerationOutput",
]
