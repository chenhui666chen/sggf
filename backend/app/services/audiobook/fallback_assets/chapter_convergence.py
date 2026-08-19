"""章节渲染结果收敛（指导文档阶段 7 生产管线接入）。

把 ChapterScenePipeline 的渲染结果（SceneRenderResult 形态）收敛为
三态生产处置、按场景回退素材计划与章节汇总：Seed 全通过章节零回退
素材成本，legacy_stems 场景按开关分流回退或人工，全部对用户与账单
可见。渲染结果按 duck-typing 消费，不反向依赖 scene_engine。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple

from ..hashing import canonical_hash
from .fallback_plan import SceneFallbackInput, build_fallback_plan, FallbackAssetPlan
from .fallback_policy import FallbackAssetPolicy
from .production_state import (
    SceneProductionDisposition,
    chapter_production_summary,
    resolve_scene_disposition,
)

CONVERGENCE_CONTRACT_NAME = "chapter_production_convergence"

# legacy 分轨回退路径需要的素材类型（SFX/BGM 两轨）。
LEGACY_FALLBACK_ASSET_KINDS = ("sfx", "bgm")

# 渲染器输出的合法场景状态（scene_renderer.SceneRenderResult.status）。
_RENDER_STATUSES = ("passed", "legacy_stems")


def _fallback_input_from_render_result(result: Any) -> SceneFallbackInput:
    scene_id = str(getattr(result, "scene_id", "") or "").strip()
    status = str(getattr(result, "status", "") or "").strip()
    if status not in _RENDER_STATUSES:
        raise ValueError(
            f"unknown scene render status for convergence: {status!r}"
        )
    if status == "passed":
        return SceneFallbackInput(
            scene_id=scene_id,
            status="passed",
            asset_kinds=(),
            reason_code="",
        )
    fallback_reason = str(getattr(result, "fallback_reason", "") or "").strip()
    return SceneFallbackInput(
        scene_id=scene_id,
        status="failed",
        asset_kinds=LEGACY_FALLBACK_ASSET_KINDS,
        reason_code=fallback_reason or "legacy_stems",
    )


@dataclass(frozen=True)
class ChapterProductionConvergence:
    """章节生产收敛结果：三态处置 + 回退素材计划 + 汇总。"""

    dispositions: Tuple[SceneProductionDisposition, ...]
    fallback_plan: FallbackAssetPlan
    summary: Mapping[str, Any]

    @property
    def convergence_hash(self) -> str:
        return canonical_hash(
            {
                "disposition_hashes": [
                    d.disposition_hash for d in self.dispositions
                ],
                "fallback_plan_hash": self.fallback_plan.plan_hash,
            },
            contract_name=CONVERGENCE_CONTRACT_NAME,
            contract_version="1.0.0",
        )


def converge_chapter_production(
    render_results: Sequence[Any],
    policy: FallbackAssetPolicy,
) -> ChapterProductionConvergence:
    """确定性收敛：渲染状态 → 回退输入 → 处置/计划/汇总。"""
    results = list(render_results)
    if not results:
        raise ValueError("chapter must contain at least one render result")

    inputs = [_fallback_input_from_render_result(result) for result in results]
    fallback_plan = build_fallback_plan(inputs, policy)

    dispositions = tuple(
        resolve_scene_disposition(
            scene_input.scene_id,
            seed_passed=scene_input.status == "passed",
            policy=policy,
        )
        for scene_input in inputs
    )
    summary = chapter_production_summary(dispositions)

    return ChapterProductionConvergence(
        dispositions=dispositions,
        fallback_plan=fallback_plan,
        summary=summary,
    )


__all__ = [
    "ChapterProductionConvergence",
    "LEGACY_FALLBACK_ASSET_KINDS",
    "converge_chapter_production",
]
