"""SceneVoiceBindingPlanner：纯领域场景 reference 槽位规划（指导文档 §7.6–§7.8）。

职责边界（§7.4 三层声音决策分离）：只决定本场哪些角色占用最多三条
reference 槽位；声音身份来自 VoiceIdentityRegistry，事件表演由导演计划
负责。规划确定性：评分常量版本化，排序不依赖输入顺序与字典遍历顺序。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .voice_identity import VoiceIdentity, VoiceIdentityRegistry

BINDING_POLICY_VERSION = "1.0.0"
MAX_SCENE_REFERENCES = 3

# §7.7 评分项（版本化常量，变化必须提升 BINDING_POLICY_VERSION）。
SCORE_EXPLICIT_BINDING = 1000
SCORE_SCENE_CORE = 500
SCORE_DURATION_TOP3 = 300
SCORE_ADJACENT_CONTINUITY = 200
SCORE_NARRATOR_PRESENT = 180
SCORE_MULTI_INTERJECTION = 120
SCORE_SINGLE_SHORT_INTERJECTION = 20
# 旁白加分要求本场实际旁白达到可辨识量（避免 0.x 秒噪声触发加分）。
NARRATOR_MIN_DURATION_S = 2.0

DECISION_REFERENCE = "reference"
DECISION_DESCRIPTION = "description"
DECISION_SPLIT_REQUIRED = "split_required"
DECISION_REJECT = "reject"

REASON_SELECTED_EXPLICIT = "selected_explicit_binding"
REASON_SELECTED_CORE = "selected_scene_core"
REASON_SELECTED_CONTINUITY = "selected_continuity"
REASON_SELECTED_NARRATOR = "selected_narrator"
REASON_DEGRADED_NO_REFERENCE = "degraded_no_legal_reference"
REASON_DEGRADED_BUDGET = "degraded_reference_budget"
REASON_SPLIT_STRICT = "split_required_strict_bindings"
REASON_REJECTED_UNAVAILABLE = "rejected_identity_unavailable"


@dataclass(frozen=True)
class SceneSpeakerFacts:
    """本场单个 speaker 的确定性事实（由事件统计得出，不含任何推断）。"""

    speaker: str
    identifiable_duration_s: float = 0.0
    has_foreground_speech: bool = False
    is_scene_core: bool = False
    is_narrator: bool = False
    background_interjection_count: int = 0
    overlap_speech_count: int = 0
    appears_in_adjacent_scene: bool = False
    first_appearance_order: int = 0
    explicit_strict_request: bool = False
    occupies_reference_budget: bool = True


@dataclass(frozen=True)
class SceneVoiceBinding:
    speaker: str
    identity_source: str
    reference: Optional[Dict[str, str]]
    description: str
    priority_score: int
    required_stability: bool
    slot_index: Optional[int]
    decision: str
    reason_code: str


@dataclass(frozen=True)
class SceneVoiceBindingPlan:
    scene_id: str
    bindings: Tuple[SceneVoiceBinding, ...]
    reference_count: int
    registry_version: str
    policy_version: str


class SceneVoiceBindingPlanner:
    def __init__(self, *, max_references: int = MAX_SCENE_REFERENCES) -> None:
        if max_references <= 0:
            raise ValueError("max_references must be positive")
        self.max_references = max_references

    def plan(
        self,
        *,
        scene_id: str,
        registry: VoiceIdentityRegistry,
        speakers: Sequence[SceneSpeakerFacts],
    ) -> SceneVoiceBindingPlan:
        facts = self._dedupe_by_identity(
            [fact for fact in speakers if fact.occupies_reference_budget],
            registry,
        )
        scored: List[Tuple[SceneSpeakerFacts, VoiceIdentity | None, int]] = []
        top3_speakers = self._duration_top3(facts)
        for fact in facts:
            identity = registry.lookup(fact.speaker)
            score = self._score(fact, identity, top3_speakers)
            scored.append((fact, identity, score))

        strict_candidates = [
            (fact, identity, score)
            for fact, identity, score in scored
            if identity is not None
            and identity.strict_stability
            and fact.has_foreground_speech
            and identity.has_legal_reference
        ]
        if len(strict_candidates) > self.max_references:
            bindings = tuple(
                self._binding(fact, identity, score, decision=DECISION_SPLIT_REQUIRED, reason_code=REASON_SPLIT_STRICT, slot_index=None)
                for fact, identity, score in self._sort_candidates(scored)
            )
            return SceneVoiceBindingPlan(
                scene_id=scene_id,
                bindings=bindings,
                reference_count=0,
                registry_version=registry.version,
                policy_version=BINDING_POLICY_VERSION,
            )

        ordered = self._sort_candidates(
            [
                (fact, identity, score)
                for fact, identity, score in scored
                if identity is not None and identity.has_legal_reference
            ]
        )
        selected = ordered[: self.max_references]
        selected_speakers = {fact.speaker for fact, _, _ in selected}
        bindings: List[SceneVoiceBinding] = []
        for slot, (fact, identity, score) in enumerate(selected, start=1):
            bindings.append(
                self._binding(
                    fact,
                    identity,
                    score,
                    decision=DECISION_REFERENCE,
                    reason_code=self._selection_reason(fact, identity),
                    slot_index=slot,
                )
            )
        for fact, identity, score in ordered[len(selected):]:
            bindings.append(
                self._binding(
                    fact,
                    identity,
                    score,
                    decision=DECISION_DESCRIPTION,
                    reason_code=REASON_DEGRADED_BUDGET,
                    slot_index=None,
                )
            )
        for fact, identity, score in scored:
            if identity is None or not identity.has_legal_reference:
                bindings.append(
                    self._binding(
                        fact,
                        identity,
                        score,
                        decision=DECISION_DESCRIPTION,
                        reason_code=REASON_DEGRADED_NO_REFERENCE,
                        slot_index=None,
                    )
                )
        bindings.sort(
            key=lambda binding: (
                binding.slot_index is None,
                binding.slot_index if binding.slot_index is not None else 0,
                -binding.priority_score,
                binding.speaker,
            )
        )
        return SceneVoiceBindingPlan(
            scene_id=scene_id,
            bindings=tuple(bindings),
            reference_count=len(selected_speakers),
            registry_version=registry.version,
            policy_version=BINDING_POLICY_VERSION,
        )

    # ---- 内部辅助 -------------------------------------------------------

    @staticmethod
    def _dedupe_by_identity(
        facts: Sequence[SceneSpeakerFacts], registry: VoiceIdentityRegistry
    ) -> List[SceneSpeakerFacts]:
        """同一 reference 身份不得重复占用槽位：保留时长更长的角色。"""
        best_by_source: Dict[str, SceneSpeakerFacts] = {}
        no_identity: List[SceneSpeakerFacts] = []
        for fact in sorted(facts, key=lambda item: item.speaker):
            identity = registry.lookup(fact.speaker)
            key = identity.source_id if identity is not None and identity.source_id else ""
            if not key:
                no_identity.append(fact)
                continue
            existing = best_by_source.get(key)
            if existing is None or (
                fact.identifiable_duration_s, -fact.first_appearance_order
            ) > (existing.identifiable_duration_s, -existing.first_appearance_order):
                best_by_source[key] = fact
        return sorted(best_by_source.values(), key=lambda item: item.speaker) + no_identity

    @staticmethod
    def _duration_top3(facts: Sequence[SceneSpeakerFacts]) -> frozenset:
        ranked = sorted(
            facts,
            key=lambda item: (-item.identifiable_duration_s, item.first_appearance_order, item.speaker),
        )
        return frozenset(fact.speaker for fact in ranked[:3])

    @staticmethod
    def _score(
        fact: SceneSpeakerFacts,
        identity: VoiceIdentity | None,
        top3_speakers: frozenset,
    ) -> int:
        score = 0
        if fact.explicit_strict_request or (identity is not None and identity.explicitly_bound):
            score += SCORE_EXPLICIT_BINDING
        if fact.is_scene_core:
            score += SCORE_SCENE_CORE
        if fact.speaker in top3_speakers:
            score += SCORE_DURATION_TOP3
        if fact.appears_in_adjacent_scene:
            score += SCORE_ADJACENT_CONTINUITY
        if fact.is_narrator and fact.identifiable_duration_s >= NARRATOR_MIN_DURATION_S:
            score += SCORE_NARRATOR_PRESENT
        if fact.background_interjection_count >= 2 or fact.overlap_speech_count >= 2:
            score += SCORE_MULTI_INTERJECTION
        elif (
            not fact.has_foreground_speech
            and fact.identifiable_duration_s <= 1.0
            and (fact.background_interjection_count == 1 or fact.overlap_speech_count == 1)
        ):
            score += SCORE_SINGLE_SHORT_INTERJECTION
        return score

    @staticmethod
    def _sort_candidates(
        candidates: Sequence[Tuple[SceneSpeakerFacts, VoiceIdentity | None, int]],
    ) -> List[Tuple[SceneSpeakerFacts, VoiceIdentity | None, int]]:
        return sorted(
            candidates,
            key=lambda item: (
                -item[2],
                not (item[1].strict_stability if item[1] is not None else False),
                -item[0].identifiable_duration_s,
                item[0].first_appearance_order,
                item[0].speaker,
            ),
        )

    @staticmethod
    def _selection_reason(fact: SceneSpeakerFacts, identity: VoiceIdentity | None) -> str:
        if fact.explicit_strict_request or (identity is not None and identity.explicitly_bound):
            return REASON_SELECTED_EXPLICIT
        if fact.is_scene_core:
            return REASON_SELECTED_CORE
        if fact.is_narrator and fact.identifiable_duration_s >= NARRATOR_MIN_DURATION_S:
            return REASON_SELECTED_NARRATOR
        if fact.appears_in_adjacent_scene:
            return REASON_SELECTED_CONTINUITY
        return REASON_SELECTED_CORE

    @staticmethod
    def _binding(
        fact: SceneSpeakerFacts,
        identity: VoiceIdentity | None,
        score: int,
        *,
        decision: str,
        reason_code: str,
        slot_index: int | None,
    ) -> SceneVoiceBinding:
        reference = None
        if decision == DECISION_REFERENCE and identity is not None and identity.provider_reference is not None:
            reference = dict(identity.provider_reference)
        return SceneVoiceBinding(
            speaker=fact.speaker,
            identity_source=identity.source if identity is not None else "",
            reference=reference,
            description=identity.description if identity is not None else "",
            priority_score=score,
            required_stability=identity.strict_stability if identity is not None else False,
            slot_index=slot_index,
            decision=decision,
            reason_code=reason_code,
        )


__all__ = [
    "BINDING_POLICY_VERSION",
    "DECISION_DESCRIPTION",
    "DECISION_REFERENCE",
    "DECISION_REJECT",
    "DECISION_SPLIT_REQUIRED",
    "MAX_SCENE_REFERENCES",
    "REASON_DEGRADED_BUDGET",
    "REASON_DEGRADED_NO_REFERENCE",
    "REASON_REJECTED_UNAVAILABLE",
    "REASON_SELECTED_CONTINUITY",
    "REASON_SELECTED_CORE",
    "REASON_SELECTED_EXPLICIT",
    "REASON_SELECTED_NARRATOR",
    "REASON_SPLIT_STRICT",
    "SceneSpeakerFacts",
    "SceneVoiceBinding",
    "SceneVoiceBindingPlan",
    "SceneVoiceBindingPlanner",
]
