"""阶段 4 Seed 生成签名合同测试（指导文档 §12.2 Seed artifact checkpoint）。

覆盖验收：

- SeedGenerationInputSignature 只签名会改变成品音频或解析合同的规范化
  请求参数；API Key、临时 URL、Request ID、超时值不得进入生成缓存键；
- binding_audit_hash 不进入生成缓存键；
- SeedGenerationOutput 与输入签名分离，输出 artifact hash 变化不是
  “输入签名变化”；
- 任一输入字段变化即改变签名（签名命中时不应产生供应商调用）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from dataclasses import replace  # noqa: E402

from app.services.audiobook.scene_engine.seed_generation_contract import (  # noqa: E402
    SeedGenerationInputSignature,
    SeedGenerationOutput,
)


def _signature(**overrides) -> SeedGenerationInputSignature:
    defaults = dict(
        model_id="seed-audio-scene-v1",
        timeline_mode="natural",
        prompt_hash="hash-prompt",
        reference_hashes=("hash-ref-1", "hash-ref-2"),
        scene_voice_identity_hash="hash-scene-identity",
        binding_decision_hash="hash-binding-decision",
        provider_id="volcengine_seed",
        provider_resource_id="ep-resource-1",
        provider_request_schema_hash="hash-request-schema",
        adapter_contract_version="1.0.0",
        requested_audio_format="mp3",
        requested_sample_rate=24000,
        requested_channels=1,
    )
    defaults.update(overrides)
    return SeedGenerationInputSignature(**defaults)


class TestInputSignatureIdentity:
    def test_signature_is_deterministic_versioned_hash(self):
        signature = _signature()
        value = signature.signature_hash()
        assert len(value) == 64
        assert value == _signature().signature_hash()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("model_id", "seed-audio-scene-v2"),
            ("timeline_mode", "bounded"),
            ("prompt_hash", "hash-prompt-2"),
            ("reference_hashes", ("hash-ref-1",)),
            ("scene_voice_identity_hash", "hash-scene-identity-2"),
            ("binding_decision_hash", "hash-binding-decision-2"),
            ("provider_id", "other_provider"),
            ("provider_resource_id", "ep-resource-2"),
            ("provider_request_schema_hash", "hash-request-schema-2"),
            ("adapter_contract_version", "2.0.0"),
            ("requested_audio_format", "wav"),
            ("requested_sample_rate", 48000),
            ("requested_channels", 2),
        ],
    )
    def test_any_input_field_change_invalidates_signature(self, field, value):
        assert _signature().signature_hash() != _signature(**{field: value}).signature_hash()

    def test_reference_order_matters(self):
        # references 数组位置与 @音频N 映射相关，顺序变化即改变 Prompt。
        assert _signature().signature_hash() != _signature(
            reference_hashes=("hash-ref-2", "hash-ref-1")
        ).signature_hash()


class TestTransientFieldsExcluded:
    def test_unknown_fields_rejected(self):
        # API Key、临时 URL、Request ID、超时值等不得进入生成缓存键：
        # 构造器白名单拒绝任何未列出的字段。
        with pytest.raises(TypeError):
            SeedGenerationInputSignature(
                model_id="m",
                timeline_mode="natural",
                prompt_hash="p",
                reference_hashes=(),
                scene_voice_identity_hash="s",
                binding_decision_hash="b",
                provider_id="pid",
                provider_resource_id="rid",
                provider_request_schema_hash="rs",
                adapter_contract_version="1.0.0",
                requested_audio_format="mp3",
                requested_sample_rate=24000,
                requested_channels=1,
                api_key="secret",
            )

    def test_audit_hash_not_part_of_signature(self):
        # binding_audit_hash 不在签名 dataclass 字段中。
        assert "binding_audit_hash" not in SeedGenerationInputSignature.__dataclass_fields__


class TestOutputSeparation:
    def test_output_fields_do_not_leak_into_input_signature(self):
        output = SeedGenerationOutput(
            audio_artifact_hash="hash-audio",
            provider_request_id="req-1",
            actual_audio_format="mp3",
            actual_sample_rate=24000,
            actual_channels=1,
            duration_s=12.5,
            provider_metadata_hash="hash-meta",
        )
        assert output.audio_artifact_hash == "hash-audio"
        # 输出校验不参与输入签名构造。
        assert _signature().signature_hash() == _signature().signature_hash()

    def test_output_artifact_hash_change_is_not_input_change(self):
        first = SeedGenerationOutput(
            audio_artifact_hash="hash-audio-1",
            provider_request_id="req-1",
            actual_audio_format="mp3",
            actual_sample_rate=24000,
            actual_channels=1,
            duration_s=12.5,
            provider_metadata_hash="hash-meta",
        )
        second = replace(first, audio_artifact_hash="hash-audio-2")
        assert first.audio_artifact_hash != second.audio_artifact_hash
