"""阶段 4 声音绑定规划：VoiceIdentityRegistry 与 SceneVoiceBindingPlanner 测试。

覆盖指导文档 §7.5/§7.6/§7.7/§7.8 与阶段 4 验收：

- 用户显式绑定不会被静默替换；
- 最多三条 reference，slot_index 连续；
- 四人以上场景确定性产生可审计降级（degraded_reference_budget）
  或明确拒绝（split_required_strict_bindings）；
- 评分常量与排序规则版本化、确定性（不依赖输入顺序）；
- 规划输出包含被选中与未选中的角色，降级可观测。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.voice_binding_planner import (  # noqa: E402
    BINDING_POLICY_VERSION,
    SceneSpeakerFacts,
    SceneVoiceBindingPlanner,
)
from app.services.audiobook.scene_engine.voice_identity import (  # noqa: E402
    VoiceIdentity,
    build_voice_identity_registry,
)


def _identity(speaker, *, source="user_private", source_id=None, description="", explicitly_bound=False, strict_stability=False):
    return {
        "speaker": speaker,
        "source": source,
        "source_id": source_id or f"{speaker}-asset",
        "provider_reference": {"audio_data": f"ref-{speaker}"},
        "description": description or f"{speaker}的声音",
        "explicitly_bound": explicitly_bound,
        "strict_stability": strict_stability,
        "asset_revision": "rev-1",
    }


def _registry(*configs, version="registry-v1"):
    return build_voice_identity_registry(configs, version=version)


def _facts(speaker, **overrides) -> SceneSpeakerFacts:
    return SceneSpeakerFacts(speaker=speaker, **overrides)


class TestVoiceIdentityRegistry:
    def test_registry_is_readonly_and_versioned(self):
        registry = _registry(_identity("林川"), _identity("苏眠"))
        assert registry.version == "registry-v1"
        assert len(registry.identities) == 2
        assert all(isinstance(item, VoiceIdentity) for item in registry.identities)

    def test_explicit_binding_wins_over_conflicting_source(self):
        # §7.5：优先级用于解决冲突，不允许静默覆盖用户显式选择。
        registry = _registry(
            _identity("林川", source="seed_speaker", source_id="auto-1"),
            _identity("林川", source="user_private", source_id="user-1", explicitly_bound=True),
        )
        identity = registry.lookup("林川")
        assert identity is not None
        assert identity.explicitly_bound is True
        assert identity.source_id == "user-1"

    def test_lookup_is_case_and_space_insensitive(self):
        registry = _registry(_identity("林川"))
        assert registry.lookup(" 林川 ") is not None

    def test_unknown_speaker_returns_none(self):
        registry = _registry(_identity("林川"))
        assert registry.lookup("路人甲") is None


class TestSlotAllocation:
    def _planner(self):
        return SceneVoiceBindingPlanner()

    def test_within_budget_all_get_contiguous_slots(self):
        registry = _registry(_identity("林川"), _identity("苏眠"))
        plan = self._planner().plan(
            scene_id="scene_0001",
            registry=registry,
            speakers=[
                _facts("林川", identifiable_duration_s=30.0, has_foreground_speech=True),
                _facts("苏眠", identifiable_duration_s=20.0, has_foreground_speech=True),
            ],
        )
        references = [binding for binding in plan.bindings if binding.decision == "reference"]
        assert len(references) == 2
        assert [binding.slot_index for binding in references] == [1, 2]
        assert plan.reference_count == 2

    def test_over_budget_degrades_lowest_score_to_description(self):
        registry = _registry(
            _identity("林川"), _identity("苏眠"), _identity("周远"), _identity("旁白")
        )
        plan = self._planner().plan(
            scene_id="scene_0001",
            registry=registry,
            speakers=[
                _facts("林川", identifiable_duration_s=30.0, has_foreground_speech=True, is_scene_core=True),
                _facts("苏眠", identifiable_duration_s=25.0, has_foreground_speech=True),
                _facts("周远", identifiable_duration_s=20.0, has_foreground_speech=True),
                _facts("旁白", identifiable_duration_s=5.0, is_narrator=True),
            ],
        )
        references = [binding for binding in plan.bindings if binding.decision == "reference"]
        degraded = [binding for binding in plan.bindings if binding.decision == "description"]
        assert len(references) == 3
        assert [binding.slot_index for binding in references] == [1, 2, 3]
        assert len(degraded) == 1
        assert degraded[0].speaker == "旁白"
        assert degraded[0].reason_code == "degraded_reference_budget"

    def test_strict_overflow_returns_split_required(self):
        # 四名严格绑定且均有可辨识台词 → 无法静默降级，返回 split_required。
        registry = _registry(
            *[
                _identity(name, strict_stability=True, explicitly_bound=True)
                for name in ("林川", "苏眠", "周远", "陈默")
            ]
        )
        plan = self._planner().plan(
            scene_id="scene_0001",
            registry=registry,
            speakers=[
                _facts(name, identifiable_duration_s=10.0, has_foreground_speech=True)
                for name in ("林川", "苏眠", "周远", "陈默")
            ],
        )
        split = [binding for binding in plan.bindings if binding.decision == "split_required"]
        assert len(split) == 4
        assert all(binding.reason_code == "split_required_strict_bindings" for binding in split)
        assert plan.reference_count == 0

    def test_explicit_binding_never_silently_replaced(self):
        registry = _registry(
            _identity("林川", explicitly_bound=True),
            _identity("苏眠"),
            _identity("周远"),
            _identity("陈默"),
        )
        plan = self._planner().plan(
            scene_id="scene_0001",
            registry=registry,
            speakers=[
                _facts("林川", identifiable_duration_s=1.0),
                _facts("苏眠", identifiable_duration_s=30.0, is_scene_core=True),
                _facts("周远", identifiable_duration_s=25.0),
                _facts("陈默", identifiable_duration_s=20.0),
            ],
        )
        by_speaker = {binding.speaker: binding for binding in plan.bindings}
        assert by_speaker["林川"].decision == "reference"
        assert by_speaker["林川"].reason_code == "selected_explicit_binding"

    def test_no_legal_reference_uses_description(self):
        registry = _registry(
            {"speaker": "路人甲", "source": "description", "source_id": "", "provider_reference": None, "description": "低沉男声", "explicitly_bound": False, "strict_stability": False, "asset_revision": ""}
        )
        plan = self._planner().plan(
            scene_id="scene_0001",
            registry=registry,
            speakers=[_facts("路人甲", identifiable_duration_s=5.0)],
        )
        binding = plan.bindings[0]
        assert binding.decision == "description"
        assert binding.reason_code == "degraded_no_legal_reference"
        assert binding.slot_index is None

    def test_duplicate_identity_occupies_single_slot(self):
        # 同一 source_id 的两个角色名共享身份，只占一个槽位。
        registry = _registry(
            _identity("林川", source_id="shared-1"),
            _identity("黑衣人", source_id="shared-1"),
        )
        plan = self._planner().plan(
            scene_id="scene_0001",
            registry=registry,
            speakers=[
                _facts("林川", identifiable_duration_s=20.0, has_foreground_speech=True),
                _facts("黑衣人", identifiable_duration_s=3.0),
            ],
        )
        references = [binding for binding in plan.bindings if binding.decision == "reference"]
        assert len(references) == 1
        assert references[0].speaker == "林川"


class TestScoringDeterminism:
    def test_result_independent_of_input_order(self):
        registry = _registry(
            _identity("林川"), _identity("苏眠"), _identity("周远"), _identity("陈默")
        )
        facts = [
            _facts("林川", identifiable_duration_s=30.0, is_scene_core=True, first_appearance_order=0),
            _facts("苏眠", identifiable_duration_s=25.0, has_foreground_speech=True, first_appearance_order=1),
            _facts("周远", identifiable_duration_s=20.0, appears_in_adjacent_scene=True, first_appearance_order=2),
            _facts("陈默", identifiable_duration_s=2.0, first_appearance_order=3),
        ]
        planner = SceneVoiceBindingPlanner()
        forward = planner.plan(scene_id="s", registry=registry, speakers=facts)
        backward = planner.plan(scene_id="s", registry=registry, speakers=list(reversed(facts)))
        assert [binding.speaker for binding in forward.bindings] == [
            binding.speaker for binding in backward.bindings
        ]
        assert [binding.slot_index for binding in forward.bindings] == [
            binding.slot_index for binding in backward.bindings
        ]

    def test_narrator_bonus_applies_only_when_narration_present(self):
        registry = _registry(_identity("旁白"), _identity("林川"), _identity("苏眠"), _identity("周远"))
        planner = SceneVoiceBindingPlanner()
        plan = planner.plan(
            scene_id="s",
            registry=registry,
            speakers=[
                _facts("旁白", identifiable_duration_s=0.5, is_narrator=True),
                _facts("林川", identifiable_duration_s=30.0),
                _facts("苏眠", identifiable_duration_s=20.0),
                _facts("周远", identifiable_duration_s=10.0, background_interjection_count=3),
            ],
        )
        by_speaker = {binding.speaker: binding for binding in plan.bindings}
        assert by_speaker["周远"].decision == "reference"  # +120 多次插话 > 旁白 0.5s
        assert by_speaker["旁白"].decision == "description"

    def test_plan_records_policy_and_registry_versions(self):
        registry = _registry(_identity("林川"), version="reg-42")
        plan = SceneVoiceBindingPlanner().plan(
            scene_id="s", registry=registry, speakers=[_facts("林川", identifiable_duration_s=5.0)]
        )
        assert plan.registry_version == "reg-42"
        assert plan.policy_version == BINDING_POLICY_VERSION

    def test_group_voice_without_identity_skips_reference_budget(self):
        registry = _registry(_identity("林川"))
        plan = SceneVoiceBindingPlanner().plan(
            scene_id="s",
            registry=registry,
            speakers=[
                _facts("林川", identifiable_duration_s=20.0),
                _facts("人群", occupies_reference_budget=False),
            ],
        )
        assert all(binding.speaker != "人群" for binding in plan.bindings)
        assert plan.reference_count == 1
