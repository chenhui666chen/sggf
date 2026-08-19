"""DirectorInputSignature：导演计划 checkpoint 唯一缓存键（指导文档 §12.2）。

按批次或场景输入范围签名，完整列出全部源事实哈希；任一字段变化即使对应
导演 checkpoint 失效，Omni 评审 Prompt 修改不在签名内、不使其失效。
"""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from ..hashing import canonical_hash

DIRECTOR_INPUT_SIGNATURE_CONTRACT_NAME = "seed_scene_director_input"
DIRECTOR_INPUT_SIGNATURE_CONTRACT_VERSION = "1.0.0"


def build_director_input_signature(
    *,
    source_segments_hash: str,
    source_segment_range: Tuple[int, int],
    reviewed_analysis_artifact_hashes: Sequence[str] = (),
    scene_context_source_hash: str,
    character_profiles_hash: str,
    capability_contract_version: str,
    director_model_id: str,
    director_prompt_hash: str,
    director_schema_hash: str,
    policy_hash: str,
    policy_version: str,
) -> str:
    """计算导演输入签名（canonical_hash，版本化合同身份）。"""
    payload = {
        "source_segments_hash": source_segments_hash,
        "source_segment_range": tuple(source_segment_range),
        "reviewed_analysis_artifact_hashes": tuple(reviewed_analysis_artifact_hashes),
        "scene_context_source_hash": scene_context_source_hash,
        "character_profiles_hash": character_profiles_hash,
        "capability_contract_version": capability_contract_version,
        "director_model_id": director_model_id,
        "director_prompt_hash": director_prompt_hash,
        "director_schema_hash": director_schema_hash,
        "policy_hash": policy_hash,
        "policy_version": policy_version,
    }
    return canonical_hash(
        payload,
        contract_name=DIRECTOR_INPUT_SIGNATURE_CONTRACT_NAME,
        contract_version=DIRECTOR_INPUT_SIGNATURE_CONTRACT_VERSION,
    )


__all__ = [
    "DIRECTOR_INPUT_SIGNATURE_CONTRACT_NAME",
    "DIRECTOR_INPUT_SIGNATURE_CONTRACT_VERSION",
    "build_director_input_signature",
]
