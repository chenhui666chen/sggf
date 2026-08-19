"""导演事件进入 Prompt 编译消费（指导文档 §9/§4.2，阶段 7 管线接入）。

把 use_v2_direction 集成决策携带的事件序列送入 ScenePromptCompiler：

- 场景描述从导演 context 确定性派生（时间、地点、声学空间、环境状态）；
- 台词逐字事实守卫：导演声明的说话人必须与审定源片段一致，
  speech 指令必须覆盖声明的源片段；台词文本由编译层按
  source_segment_index 从源片段读取，不信任导演副本；
- 时长预算核验：§8.1 估算总时长不超过规划硬上限（与 ScenePlanner
  默认 hard_max_duration_s 一致）；
- degrade_v1 / manual_review 决策不携带可编译事件，显式拒绝。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any, Sequence

from ..scene_direction.pipeline_integration import DirectorIntegrationDecision
from .models import ScenePromptCompileResult, SceneRenderPlan, SceneVoiceProfile
from .planner import ScenePlanner
from .prompt_compiler import ScenePromptCompiler

# 规划硬上限（秒）：与 ScenePlanner 默认 hard_max_duration_s 一致。
DURATION_BUDGET_PLANNING_MAX_S = 105.0

_ACTION_USE_V2 = "use_v2_direction"


def derive_scene_description(context: Any) -> str:
    """从导演 context 确定性派生顶层场景描述；无内容时返回空串。"""
    parts = [
        str(value).strip()
        for value in (
            getattr(context, "time", ""),
            getattr(context, "location", ""),
            getattr(context, "acoustic_space", ""),
            getattr(context, "ambient_state", ""),
        )
        if str(value).strip()
    ]
    return "，".join(parts)


def verify_director_dialogue_fidelity(
    decision: DirectorIntegrationDecision,
    segments: Sequence[Any],
    compiler: ScenePromptCompiler | None = None,
) -> None:
    """台词逐字事实守卫：speech 事件与源片段说话人/台词逐字一致。

    compiler 参数为签名预留（后续可扩展 expected_texts 级校验），
    当前守卫只依赖导演计划与源片段事实。
    """
    del compiler
    if decision.action != _ACTION_USE_V2:
        raise ValueError(
            f"dialogue fidelity guard requires use_v2_direction, got {decision.action!r}"
        )
    for direction in decision.directions:
        covered = []
        for speech in direction.speech:
            segment = segments[speech.source_segment_index]
            declared_speaker = str(speech.speaker or "").strip()
            segment_speaker = str(getattr(segment, "speaker", "") or "").strip()
            if declared_speaker != segment_speaker:
                raise ValueError(
                    f"director scene {direction.scene_key} declares speaker "
                    f"{declared_speaker!r} for segment {speech.source_segment_index}, "
                    f"but reviewed source says {segment_speaker!r}"
                )
            covered.append(speech.source_segment_index)
        if covered != list(direction.source_segment_indices):
            raise ValueError(
                f"director scene {direction.scene_key} speech directives do not "
                "cover its declared source segments"
            )


def verify_duration_budget(decision: DirectorIntegrationDecision) -> float:
    """§8.1 估算总时长预算核验；返回总时长（秒）。"""
    if not decision.duration_estimates:
        raise ValueError("duration budget check requires duration estimates")
    total = sum(estimate.total_s for estimate in decision.duration_estimates)
    if total > DURATION_BUDGET_PLANNING_MAX_S:
        raise ValueError(
            f"director scene duration estimate {total:.1f}s exceeds planning "
            f"budget {DURATION_BUDGET_PLANNING_MAX_S:g}s"
        )
    return total


def compile_decision_prompt(
    decision: DirectorIntegrationDecision,
    segments: Sequence[Any],
    *,
    compiler: ScenePromptCompiler | None = None,
    voice_profiles: Sequence[SceneVoiceProfile] = (),
    ending_description: str = "",
) -> ScenePromptCompileResult:
    """单场景决策 → Prompt 编译（守卫先行，确定性输出）。"""
    if decision.action != _ACTION_USE_V2:
        raise ValueError(
            f"only use_v2_direction decisions compile to prompts, got {decision.action!r}"
        )
    if len(decision.directions) != 1 or len(decision.events_by_direction) != 1:
        raise ValueError("compile_decision_prompt supports single-scene decisions")
    verify_director_dialogue_fidelity(decision, segments)
    verify_duration_budget(decision)
    active_compiler = compiler or ScenePromptCompiler()
    scene_description = derive_scene_description(decision.directions[0].context)
    return active_compiler.compile_events(
        decision.events_by_direction[0],
        voice_profiles=voice_profiles,
        scene_description=scene_description,
        ending_description=ending_description,
    )


def apply_directed_prompt(
    plan: SceneRenderPlan,
    compiled: ScenePromptCompileResult,
) -> SceneRenderPlan:
    """把 V2 导演编排的编译结果写入渲染计划（确定性字段替换）。

    只替换 prompt/prompt_hash/expected_text/expected_vocalizations 并
    恢复 seed_scene 渲染模式（导演层已核验时长预算）；references 与
    reference_hashes 保留 V1 计划的声音绑定结果（编排层编译不携带
    voice_profiles）。requires_split 的编译结果拒绝注入。
    """
    if compiled.requires_split:
        raise ValueError(
            "directed prompt compilation requires split; keep the v1 plan"
        )
    return replace(
        plan,
        prompt=compiled.prompt,
        prompt_hash=hashlib.sha256(compiled.prompt.encode("utf-8")).hexdigest(),
        expected_text="\n".join(compiled.expected_texts),
        expected_vocalizations=ScenePlanner._expected_vocalizations(compiled),
        render_mode="seed_scene",
        fallback_reason=None,
    )


__all__ = [
    "DURATION_BUDGET_PLANNING_MAX_S",
    "apply_directed_prompt",
    "compile_decision_prompt",
    "derive_scene_description",
    "verify_director_dialogue_fidelity",
    "verify_duration_budget",
]
