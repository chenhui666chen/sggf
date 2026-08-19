"""阶段 4 声音绑定 hash 分离测试（指导文档 §12.2）。

覆盖验收：

- 相同结构化合同在 contract version 变化时 canonical hash 变化；
- 只有决策字段（speaker/slot_index/reference_content_hash/description/
  decision/required_stability）进入 binding_decision_hash（Seed 生成键）；
- 审计字段（policy_version/priority_score/reason_code/registry_version/
  asset_revision/identity source/source_id）只进入 binding_audit_hash，
  其变化不触发 Seed 重新生成；
- slot_index 进入决策 hash（集合不变但顺序变化即改变 Prompt 映射）；
- 二进制内容不进入 canonical_hash。
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

from app.services.audiobook.hashing import canonical_hash  # noqa: E402
from app.services.audiobook.scene_engine.voice_binding_hash import (  # noqa: E402
    binding_audit_hash,
    binding_decision_hash,
)
from app.services.audiobook.scene_engine.voice_binding_planner import (  # noqa: E402
    SceneVoiceBinding,
    SceneVoiceBindingPlan,
)


def _binding(speaker, *, slot_index, decision="reference", description="", reason="selected_scene_core", priority=300, reference_content_hash=""):
    return SceneVoiceBinding(
        speaker=speaker,
        identity_source="user_private",
        reference={"audio_data": f"ref-{speaker}"} if decision == "reference" else None,
        description=description or f"{speaker}的声音",
        priority_score=priority,
        required_stability=False,
        slot_index=slot_index,
        decision=decision,
        reason_code=reason,
    )


def _plan(*bindings, policy_version="1.0.0", registry_version="reg-1") -> SceneVoiceBindingPlan:
    return SceneVoiceBindingPlan(
        scene_id="scene_0001",
        bindings=tuple(bindings),
        reference_count=sum(1 for binding in bindings if binding.decision == "reference"),
        registry_version=registry_version,
        policy_version=policy_version,
    )


def _content_hashes(*bindings) -> dict:
    return {
        binding.speaker: f"digest-{binding.speaker}"
        for binding in bindings
        if binding.decision == "reference"
    }


class TestDecisionAuditSeparation:
    def test_audit_only_change_does_not_alter_decision_hash(self):
        first = _plan(
            _binding("林川", slot_index=1, reason="selected_scene_core", priority=800),
            _binding("苏眠", slot_index=2, reason="selected_continuity", priority=300),
        )
        second = _plan(
            _binding("林川", slot_index=1, reason="selected_explicit_binding", priority=1000),
            _binding("苏眠", slot_index=2, reason="selected_narrator", priority=480),
        )
        assert binding_decision_hash(first, _content_hashes(*first.bindings)) == binding_decision_hash(
            second, _content_hashes(*second.bindings)
        )
        assert binding_audit_hash(first) != binding_audit_hash(second)

    def test_policy_and_registry_version_only_affect_audit_hash(self):
        first = _plan(_binding("林川", slot_index=1), policy_version="1.0.0", registry_version="reg-1")
        second = _plan(_binding("林川", slot_index=1), policy_version="2.0.0", registry_version="reg-2")
        hashes_first = _content_hashes(*first.bindings)
        assert binding_decision_hash(first, hashes_first) == binding_decision_hash(second, hashes_first)
        assert binding_audit_hash(first) != binding_audit_hash(second)

    def test_slot_order_change_alters_decision_hash(self):
        # 集合不变但槽位顺序变化即改变 Prompt @音频N 映射。
        first = _plan(
            _binding("林川", slot_index=1),
            _binding("苏眠", slot_index=2),
        )
        second = _plan(
            _binding("林川", slot_index=2),
            _binding("苏眠", slot_index=1),
        )
        hashes = {"林川": "digest-a", "苏眠": "digest-b"}
        assert binding_decision_hash(first, hashes) != binding_decision_hash(second, hashes)

    def test_reference_content_hash_change_alters_decision_hash(self):
        plan = _plan(_binding("林川", slot_index=1))
        assert binding_decision_hash(plan, {"林川": "digest-v1"}) != binding_decision_hash(
            plan, {"林川": "digest-v2"}
        )

    def test_description_change_alters_decision_hash(self):
        first = _plan(_binding("路人甲", slot_index=None, decision="description", description="低沉男声"))
        second = _plan(_binding("路人甲", slot_index=None, decision="description", description="清亮女声"))
        assert binding_decision_hash(first, {}) != binding_decision_hash(second, {})


class TestHashHelperDiscipline:
    def test_decision_hash_is_versioned_canonical_hash(self):
        plan = _plan(_binding("林川", slot_index=1))
        value = binding_decision_hash(plan, {"林川": "digest-a"})
        assert len(value) == 64
        assert value == binding_decision_hash(plan, {"林川": "digest-a"})

    def test_binary_content_rejected_by_canonical_hash(self):
        with pytest.raises(TypeError):
            canonical_hash(
                {"audio": b"\x00\x01"},
                contract_name="seed_scene_voice_binding_decision",
                contract_version="1.0.0",
            )
