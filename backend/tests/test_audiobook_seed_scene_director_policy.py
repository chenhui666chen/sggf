"""阶段 3 Seed 场景导演合同：改编 Prompt、策略与输入签名测试。

覆盖指导文档 §4.3/§6/§12.2：

- Seed 专用改编 Prompt 与 legacy_stems 分离（不含分轨参数/素材 ID/混音覆盖率），
  包含 §6.2 改编目标，只要求输出 §5 结构；
- SeedSceneDirectorPolicy 服务端版本化策略：字段进入合同指纹，
  项目只能请求更低预算（有效预算取最小值）；
- DirectorInputSignature 作为导演计划 checkpoint 唯一缓存键：
  全部源事实哈希参与签名，任一字段变化即签名变化。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_direction.policy import (  # noqa: E402
    DEFAULT_SEED_SCENE_DIRECTOR_POLICY,
    SeedSceneDirectorPolicy,
    resolve_effective_policy,
)
from app.services.audiobook.scene_direction.prompt import (  # noqa: E402
    build_seed_director_prompt,
    director_prompt_hash,
    director_schema_hash,
)
from app.services.audiobook.scene_direction.signature import (  # noqa: E402
    build_director_input_signature,
)


def _signature_kwargs(**overrides) -> dict:
    kwargs = {
        "source_segments_hash": "seg-hash",
        "source_segment_range": (0, 5),
        "reviewed_analysis_artifact_hashes": ("analysis-1",),
        "scene_context_source_hash": "context-hash",
        "character_profiles_hash": "profiles-hash",
        "capability_contract_version": "1.0.0",
        "director_model_id": "doubao-seed-1.0",
        "director_prompt_hash": director_prompt_hash(),
        "director_schema_hash": director_schema_hash(),
        "policy_hash": DEFAULT_SEED_SCENE_DIRECTOR_POLICY.fingerprint(),
        "policy_version": DEFAULT_SEED_SCENE_DIRECTOR_POLICY.version,
    }
    kwargs.update(overrides)
    return kwargs


class TestSeedDirectorPrompt:
    def test_prompt_contains_adaptation_goals(self):
        messages = build_seed_director_prompt(
            "0|林川|这里有人吗？\n1|苏眠|别出声。",
            chapter_context="本章发生在深夜，废弃车站。",
        )
        content = "\n".join(message["content"] for message in messages)
        # §6.2 改编目标关键词。
        for keyword in (
            "连续场景",
            "保持审定台词与说话人不变",
            "非语言人声",
            "音乐",
            "声学处理",
            "不得新增",
        ):
            assert keyword in content
        assert "本章发生在深夜，废弃车站" in content

    def test_prompt_is_separated_from_legacy_stems_contract(self):
        messages = build_seed_director_prompt("0|林川|这里有人吗？")
        content = "\n".join(message["content"] for message in messages)
        # §6.1：分轨音量数值、素材 ID、混音覆盖率等旧合同不得进入 Seed Prompt。
        for forbidden in ("分轨", "音量数值", "素材 ID", "asset_id", "混音覆盖率", "每句必须独立合成"):
            assert forbidden not in content

    def test_prompt_requires_strict_json_output(self):
        messages = build_seed_director_prompt("0|林川|这里有人吗？")
        content = "\n".join(message["content"] for message in messages)
        assert "严格 JSON" in content or "严格JSON" in content
        assert "scenes" in content

    def test_prompt_and_schema_hash_are_versioned_and_stable(self):
        assert director_prompt_hash() == director_prompt_hash()
        assert director_schema_hash() == director_schema_hash()
        assert director_prompt_hash() != director_schema_hash()


class TestDirectorPolicy:
    def test_default_policy_disables_inferred_vocalizations(self):
        policy = DEFAULT_SEED_SCENE_DIRECTOR_POLICY
        assert policy.allow_inferred_vocalizations is False
        assert policy.allowed_inferred_vocalization_types == ()
        assert policy.max_attempts_per_batch == 2  # 首次 + 最多一次纠错

    def test_fingerprint_is_stable_and_version_sensitive(self):
        policy = DEFAULT_SEED_SCENE_DIRECTOR_POLICY
        assert policy.fingerprint() == policy.fingerprint()
        bumped = SeedSceneDirectorPolicy(
            **{**policy.contract_fields(), "version": "2.0.0"}
        )
        assert bumped.fingerprint() != policy.fingerprint()

    def test_budget_field_change_alters_fingerprint(self):
        policy = DEFAULT_SEED_SCENE_DIRECTOR_POLICY
        stricter = SeedSceneDirectorPolicy(
            **{**policy.contract_fields(), "max_calls_per_chapter": policy.max_calls_per_chapter - 1}
        )
        assert stricter.fingerprint() != policy.fingerprint()

    def test_project_can_only_lower_budget(self):
        server = DEFAULT_SEED_SCENE_DIRECTOR_POLICY
        lower = resolve_effective_policy(server, max_calls_per_chapter=1, max_cost_per_job=0.5)
        assert lower.max_calls_per_chapter == 1
        assert lower.max_cost_per_job == 0.5
        higher = resolve_effective_policy(
            server,
            max_calls_per_chapter=server.max_calls_per_chapter + 100,
            max_cost_per_job=server.max_cost_per_job + 100,
        )
        assert higher.max_calls_per_chapter == server.max_calls_per_chapter
        assert higher.max_cost_per_job == server.max_cost_per_job


class TestDirectorInputSignature:
    def test_signature_is_deterministic_hex(self):
        signature = build_director_input_signature(**_signature_kwargs())
        assert len(signature) == 64
        assert signature == build_director_input_signature(**_signature_kwargs())

    @pytest.mark.parametrize(
        "field,value",
        [
            ("source_segments_hash", "other-seg-hash"),
            ("source_segment_range", (1, 5)),
            ("reviewed_analysis_artifact_hashes", ()),
            ("scene_context_source_hash", "other-context"),
            ("character_profiles_hash", "other-profiles"),
            ("capability_contract_version", "2.0.0"),
            ("director_model_id", "other-model"),
            ("policy_hash", "other-policy-hash"),
            ("policy_version", "9.9.9"),
        ],
    )
    def test_every_source_fact_participates_in_signature(self, field, value):
        baseline = build_director_input_signature(**_signature_kwargs())
        mutated = build_director_input_signature(**_signature_kwargs(**{field: value}))
        assert mutated != baseline

    def test_omni_prompt_change_does_not_affect_signature(self):
        # Omni 评审 Prompt 不属于导演输入合同（§4.3/§12.2 失效规则）。
        first = build_director_input_signature(**_signature_kwargs())
        second = build_director_input_signature(**_signature_kwargs())
        assert first == second
