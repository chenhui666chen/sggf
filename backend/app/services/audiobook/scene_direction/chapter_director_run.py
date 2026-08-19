"""章节任务编排：导演前置步骤（指导文档 §4.2/§9，阶段 7 管线接入）。

章节渲染前的导演编排串接第一段：注入 LLM 客户端 →
SeedSceneDirectorService.direct_chapter → 集成决策 → 按场景编译
Prompt，产出渲染入参 ``ChapterDirectorRun``：

- use_v2_direction：按 scene_key 携带编译后的 Prompt（台词中文引号
  冻结、场景描述来自导演 context），供渲染层按场景消费；
- degrade_v1 / manual_review：不产出 Prompt，reason code 可审计，
  编排层按 V1 确定性编译路径或人工流程继续；
- 编译前守卫：导演声明的说话人必须与审定源片段一致，speech 指令
  必须覆盖声明的源片段（映射层会以源片段为准静默纠正，守卫必须
  校验声明本身而非映射后事件）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..scene_engine.models import SceneAudioEvent, ScenePromptCompileResult
from ..scene_engine.prompt_compiler import ScenePromptCompiler
from .director import DirectorBudgetLedger, SeedSceneDirector
from .models import SeedSceneDirection
from .pipeline_integration import SeedSceneDirectorService
from .policy import DEFAULT_SEED_SCENE_DIRECTOR_POLICY, SeedSceneDirectorPolicy

_ACTION_USE_V2 = "use_v2_direction"


@dataclass(frozen=True)
class ChapterDirectorRun:
    """章节导演编排结果：集成决策 + 按场景编译的渲染入参。"""

    action: str
    reason_code: str
    prompts_by_scene: Mapping[str, ScenePromptCompileResult]
    decision_hash: str = ""


async def run_chapter_direction(
    segments: Sequence[Any],
    *,
    llm_client: Any,
    director_model: str = "",
    policy: SeedSceneDirectorPolicy = DEFAULT_SEED_SCENE_DIRECTOR_POLICY,
    chapter_context: str = "",
    character_profiles_text: str = "",
    reviewed_analysis_artifact_hashes: Sequence[str] = (),
    checkpoints: Optional[List[Dict[str, Any]]] = None,
    chapter_consumed: Optional[DirectorBudgetLedger] = None,
    job_consumed: Optional[DirectorBudgetLedger] = None,
    compiler: ScenePromptCompiler | None = None,
) -> ChapterDirectorRun:
    """导演 → 决策 → 按场景编译；降级路径不产出 Prompt。"""
    director = SeedSceneDirector(
        llm_client, model=director_model, policy=policy
    )
    service = SeedSceneDirectorService(director, checkpoints=checkpoints)
    decision = await service.direct_chapter(
        segments,
        chapter_context=chapter_context,
        character_profiles_text=character_profiles_text,
        reviewed_analysis_artifact_hashes=reviewed_analysis_artifact_hashes,
        chapter_consumed=chapter_consumed,
        job_consumed=job_consumed,
    )
    if decision.action != _ACTION_USE_V2:
        return ChapterDirectorRun(
            action=decision.action,
            reason_code=decision.reason_code,
            prompts_by_scene={},
            decision_hash=decision.decision_hash,
        )
    prompts_by_scene = {
        direction.scene_key: _compile_scene(direction, events, segments, compiler)
        for direction, events in zip(
            decision.directions, decision.events_by_direction
        )
    }
    return ChapterDirectorRun(
        action=decision.action,
        reason_code=decision.reason_code,
        prompts_by_scene=prompts_by_scene,
        decision_hash=decision.decision_hash,
    )


def _compile_scene(
    direction: SeedSceneDirection,
    events: Sequence[SceneAudioEvent],
    segments: Sequence[Any],
    compiler: ScenePromptCompiler | None,
) -> ScenePromptCompileResult:
    """单场景编译：声明层守卫先行，场景描述来自导演 context。"""
    # 延迟导入避免 scene_engine 包初始化期循环依赖。
    from ..scene_engine.prompt_consume import derive_scene_description

    indices = list(direction.source_segment_indices)
    if not indices or indices != list(range(indices[0], indices[0] + len(indices))):
        raise ValueError(
            f"director scene {direction.scene_key} source segments must be "
            "a contiguous range"
        )
    declared_speech_indices = []
    for speech in direction.speech:
        segment = segments[speech.source_segment_index]
        declared = str(speech.speaker or "").strip()
        source_speaker = str(getattr(segment, "speaker", "") or "").strip()
        if declared != source_speaker:
            raise ValueError(
                f"director scene {direction.scene_key} declares speaker "
                f"{declared!r} for segment {speech.source_segment_index}, "
                f"but reviewed source says {source_speaker!r}"
            )
        declared_speech_indices.append(speech.source_segment_index)
    if declared_speech_indices != indices:
        raise ValueError(
            f"director scene {direction.scene_key} speech directives do not "
            "cover its declared source segments"
        )
    active_compiler = compiler or ScenePromptCompiler()
    return active_compiler.compile_events(
        events,
        scene_description=derive_scene_description(direction.context),
    )


__all__ = [
    "ChapterDirectorRun",
    "run_chapter_direction",
]
