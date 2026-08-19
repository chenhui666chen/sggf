"""Chapter-level orchestration for Seed Audio scene rendering."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence, Tuple

from ..fallback_assets.chapter_convergence import (
    ChapterProductionConvergence,
    converge_chapter_production,
)
from ..fallback_assets.fallback_policy import FallbackAssetPolicy
from .models import (
    DEFERRED_PREVIEW_REFERENCE_FIELD,
    ScenePromptCompileResult,
    SceneRenderPlan,
    SceneVoiceProfile,
)
from .planner import ScenePlanner
from .preview_reference_asset import (
    PreviewReferenceAsset,
    PreviewReferenceMaterializationError,
)
from .prompt_consume import apply_directed_prompt
from .scene_renderer import (
    DEFAULT_SEED_AUDIO_MODEL,
    SceneRenderResult,
)
from .voice_reference_resolver import VoiceReferenceResolver


logger = logging.getLogger(__name__)

DEFAULT_SCENE_RENDER_CONCURRENCY = 4
SCENE_RENDER_CONCURRENCY_ENV = "AUDIOBOOK_SEED_SCENE_RENDER_CONCURRENCY"


def resolve_scene_render_concurrency() -> int:
    """解析场景并发渲染数：环境变量可覆盖，非法/小于 1 时回退默认值。"""
    raw = os.getenv(SCENE_RENDER_CONCURRENCY_ENV, "")
    if not str(raw).strip():
        return DEFAULT_SCENE_RENDER_CONCURRENCY
    try:
        value = int(str(raw).strip())
    except ValueError:
        logger.warning(
            "非法场景并发配置 %s=%r，回退默认 %s",
            SCENE_RENDER_CONCURRENCY_ENV,
            raw,
            DEFAULT_SCENE_RENDER_CONCURRENCY,
        )
        return DEFAULT_SCENE_RENDER_CONCURRENCY
    return max(1, value)


@dataclass(frozen=True)
class ChapterSceneRender:
    """One finalized scene plan and its isolated render outcome."""

    plan: SceneRenderPlan
    result: SceneRenderResult
    reference_assets: Tuple[PreviewReferenceAsset, ...] = ()


@dataclass(frozen=True)
class ChapterScenePipelineResult:
    """Ordered scene outcomes for later chapter assembly."""

    scenes: Tuple[ChapterSceneRender, ...]
    # 阶段 7：注入回退资产策略时附带的生产收敛结果（三态处置+回退计划）。
    convergence: ChapterProductionConvergence | None = None

    @property
    def plans(self) -> Tuple[SceneRenderPlan, ...]:
        return tuple(scene.plan for scene in self.scenes)

    @property
    def results(self) -> Tuple[SceneRenderResult, ...]:
        return tuple(scene.result for scene in self.scenes)


class ChapterScenePipeline:
    """Coordinate planning, reference materialization, and scene rendering."""

    def __init__(
        self,
        *,
        reference_materializer: Any,
        renderer: Any,
        planner: ScenePlanner | None = None,
        voice_reference_resolver: VoiceReferenceResolver | None = None,
        provider_attempt_ledger: Any = None,
        db_session_factory: Callable[[], Any] | None = None,
        fallback_asset_policy: FallbackAssetPolicy | None = None,
        max_scene_concurrency: int | None = None,
    ) -> None:
        self.planner = planner or ScenePlanner()
        self.voice_reference_resolver = voice_reference_resolver or VoiceReferenceResolver()
        self.reference_materializer = reference_materializer
        self.renderer = renderer
        self.provider_attempt_ledger = provider_attempt_ledger
        self.db_session_factory = db_session_factory
        self.fallback_asset_policy = fallback_asset_policy
        self.max_scene_concurrency = (
            max(1, int(max_scene_concurrency))
            if max_scene_concurrency is not None
            else resolve_scene_render_concurrency()
        )

    def render(
        self,
        segments: Sequence[Any],
        *,
        voice_mapping: Mapping[str, Mapping[str, Any]] | None = None,
        descriptions: Mapping[str, str] | None = None,
        default_tts_model: str = "",
        scene_description: str = "",
        chapter_facts: Mapping[str, Any] | None = None,
        director_style: str = "",
        directed_prompts: Mapping[str, ScenePromptCompileResult] | None = None,
        model: str = DEFAULT_SEED_AUDIO_MODEL,
        audio_config: Mapping[str, Any] | None = None,
        checkpoints: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ChapterScenePipelineResult:
        if not segments:
            return ChapterScenePipelineResult(scenes=())

        resolved_mapping = voice_mapping or {}
        profiles = self.voice_reference_resolver.resolve(
            self._speaker_names(segments),
            voice_mapping=resolved_mapping,
            descriptions=descriptions,
            default_tts_model=default_tts_model,
        )
        profiles_by_name = {profile.name: profile for profile in profiles}
        topology_plans = self.planner.plan(
            segments,
            voice_profiles=profiles,
            scene_description=scene_description,
            chapter_facts=chapter_facts,
            director_style=director_style,
        )

        materialized_assets: dict[str, PreviewReferenceAsset] = {}
        materialization_errors: dict[str, str] = {}
        # 物化缓存为章节级共享状态，并发渲染时串行化检查与物化写入
        materialization_lock = threading.Lock()

        def render_topology_scene(topology_plan) -> list[ChapterSceneRender]:
            outputs: list[ChapterSceneRender] = []
            if topology_plan.render_mode != "seed_scene":
                render_result = self._render_plan(
                    topology_plan,
                    model=model,
                    audio_config=audio_config,
                    checkpoint=self._checkpoint_for(checkpoints, topology_plan.scene_id),
                )
                outputs.append(
                    ChapterSceneRender(plan=topology_plan, result=render_result)
                )
                return outputs

            scene_profiles = []
            scene_assets = []
            materialization_error = None
            for speaker_name in topology_plan.speaker_names:
                profile = profiles_by_name.get(speaker_name)
                if profile is None:
                    continue
                reference = profile.provider_reference
                if not reference or "speaker" in reference:
                    scene_profiles.append(profile)
                    continue

                config_value = resolved_mapping.get(speaker_name, {})
                config = dict(config_value) if isinstance(config_value, Mapping) else {}
                cache_key = self._materialization_key(config, reference)
                with materialization_lock:
                    if cache_key in materialization_errors:
                        materialization_error = materialization_errors[cache_key]
                    else:
                        try:
                            asset = materialized_assets.get(cache_key)
                            if asset is None:
                                asset = self.reference_materializer.materialize(
                                    self._materialization_config(config, reference)
                                )
                                materialized_assets[cache_key] = asset
                                self._persist_materialized_asset(asset, config)
                        except PreviewReferenceMaterializationError as exc:
                            materialization_error = exc.code
                            materialization_errors[cache_key] = exc.code
                if materialization_error:
                    break
                scene_profiles.append(
                    replace(profile, provider_reference=dict(asset.reference))
                )
                scene_assets.append(asset)

            if materialization_error:
                render_result = SceneRenderResult(
                    scene_id=topology_plan.scene_id,
                    status="legacy_stems",
                    action="legacy_stems",
                    attempts=0,
                    audio_path=None,
                    subtitle_payload=None,
                    quality_report=None,
                    fallback_reason=(
                        "reference_materialization_failed:"
                        f"{materialization_error}"
                    ),
                )
                outputs.append(
                    ChapterSceneRender(plan=topology_plan, result=render_result)
                )
                return outputs

            final_plan = self.planner.recompile_plan(
                topology_plan,
                segments,
                voice_profiles=scene_profiles,
                scene_description=scene_description,
                chapter_facts=chapter_facts,
                director_style=director_style,
            )
            final_plan = self._apply_directed_prompt(
                final_plan, segments, directed_prompts
            )
            resumable_split_plans = self.planner.split_plan_once(
                final_plan,
                segments,
                voice_profiles=scene_profiles,
                scene_description=scene_description,
                chapter_facts=chapter_facts,
                director_style=director_style,
            )
            if resumable_split_plans and any(
                self._checkpoint_for(checkpoints, plan.scene_id) is not None
                for plan in resumable_split_plans
            ):
                parent_checkpoint = self._checkpoint_for(
                    checkpoints,
                    final_plan.scene_id,
                )
                outputs.extend(
                    self._render_split_plans(
                        resumable_split_plans,
                        parent_plan=final_plan,
                        parent_fallback_reason=(
                            str(parent_checkpoint.get("fallback_reason") or "") or None
                            if parent_checkpoint
                            else None
                        ),
                        parent_attempts=(
                            int(parent_checkpoint.get("attempts") or 0)
                            if parent_checkpoint
                            else 0
                        ),
                        resumed=True,
                        reference_assets=tuple(scene_assets),
                        model=model,
                        audio_config=audio_config,
                        checkpoints=checkpoints,
                    )
                )
                return outputs

            render_result = self._render_plan(
                final_plan,
                model=model,
                audio_config=audio_config,
                checkpoint=self._checkpoint_for(checkpoints, final_plan.scene_id),
            )
            split_plans = ()
            if self._should_split(final_plan, render_result):
                split_plans = self.planner.split_plan_once(
                    final_plan,
                    segments,
                    voice_profiles=scene_profiles,
                    scene_description=scene_description,
                    chapter_facts=chapter_facts,
                    director_style=director_style,
                )
            if not split_plans:
                outputs.append(
                    ChapterSceneRender(
                        plan=final_plan,
                        result=render_result,
                        reference_assets=tuple(scene_assets),
                    )
                )
                return outputs
            outputs.extend(
                self._render_split_plans(
                    split_plans,
                    parent_plan=final_plan,
                    parent_fallback_reason=render_result.fallback_reason,
                    parent_attempts=render_result.attempts,
                    resumed=False,
                    reference_assets=tuple(scene_assets),
                    model=model,
                    audio_config=audio_config,
                    checkpoints=checkpoints,
                )
            )
            return outputs

        # 场景间无依赖（拆分依赖在同场景作业内串行完成），独立场景可并发
        # 渲染；按计划顺序收集结果保证装配顺序稳定。
        if self.max_scene_concurrency > 1 and len(topology_plans) > 1:
            with ThreadPoolExecutor(
                max_workers=min(self.max_scene_concurrency, len(topology_plans)),
                thread_name_prefix="scene-render",
            ) as executor:
                futures = [
                    executor.submit(render_topology_scene, plan)
                    for plan in topology_plans
                ]
                scene_outputs = [
                    scene for future in futures for scene in future.result()
                ]
        else:
            scene_outputs = [
                scene
                for plan in topology_plans
                for scene in render_topology_scene(plan)
            ]

        return ChapterScenePipelineResult(
            scenes=tuple(scene_outputs),
            convergence=self._converge(scene_outputs),
        )

    def _converge(
        self,
        scene_outputs: list[ChapterSceneRender],
    ) -> ChapterProductionConvergence | None:
        """阶段 7：按回退资产策略收敛章节生产状态。

        未注入策略时保持旧行为返回 None，调用方可自行收敛。
        """
        if self.fallback_asset_policy is None:
            return None
        return converge_chapter_production(
            [scene.result for scene in scene_outputs],
            self.fallback_asset_policy,
        )

    def _apply_directed_prompt(
        self,
        plan: SceneRenderPlan,
        segments: Sequence[Any],
        directed_prompts: Mapping[str, ScenePromptCompileResult] | None,
    ) -> SceneRenderPlan:
        """阶段 7：按 scene_id 注入 V2 导演编排的编译结果。

        末道保真防线：编译结果的 expected_texts 必须与该场景源片段
        台词逐字一致，任何不符都保留 V1 确定性计划并记录告警。
        未注入/未命中/注入失败均不影响既有行为。
        """
        if not directed_prompts:
            return plan
        compiled = directed_prompts.get(plan.scene_id)
        if compiled is None:
            return plan
        source_texts = tuple(
            str(getattr(segments[index], "text", "") or "").strip()
            for index in plan.source_segment_indices
        )
        if tuple(compiled.expected_texts) != source_texts:
            logger.warning(
                "导演编排 Prompt 与源片段台词不一致，保留 V1 计划: scene=%s",
                plan.scene_id,
            )
            return plan
        try:
            return apply_directed_prompt(plan, compiled)
        except ValueError as exc:
            logger.warning(
                "导演编排 Prompt 注入失败，保留 V1 计划: scene=%s error=%s",
                plan.scene_id,
                exc,
            )
            return plan

    def _render_split_plans(
        self,
        split_plans: Sequence[SceneRenderPlan],
        *,
        parent_plan: SceneRenderPlan,
        parent_fallback_reason: str | None,
        parent_attempts: int,
        resumed: bool,
        reference_assets: Tuple[PreviewReferenceAsset, ...],
        model: str,
        audio_config: Mapping[str, Any] | None,
        checkpoints: Mapping[str, Mapping[str, Any]] | None,
    ) -> list[ChapterSceneRender]:
        outputs = []
        for split_plan in split_plans:
            split_result = self._render_plan(
                split_plan,
                model=model,
                audio_config=audio_config,
                checkpoint=self._checkpoint_for(checkpoints, split_plan.scene_id),
            )
            split_metadata = dict(split_result.metadata or {})
            split_metadata.update(
                {
                    "split_parent_scene_id": parent_plan.scene_id,
                    "split_parent_fallback_reason": parent_fallback_reason,
                    "split_parent_attempts": parent_attempts,
                    "resumed_split_topology": resumed,
                }
            )
            outputs.append(
                ChapterSceneRender(
                    plan=split_plan,
                    result=replace(split_result, metadata=split_metadata),
                    reference_assets=reference_assets,
                )
            )
        return outputs

    @staticmethod
    def _should_split(
        plan: SceneRenderPlan,
        result: SceneRenderResult,
    ) -> bool:
        if len(plan.source_segment_indices) < 2:
            return False
        if result.status != "legacy_stems" or result.quality_report is None:
            return False
        return not bool(getattr(result.quality_report, "passed", False))

    def _render_plan(
        self,
        plan: SceneRenderPlan,
        *,
        model: str,
        audio_config: Mapping[str, Any] | None,
        checkpoint: Mapping[str, Any] | None,
    ) -> SceneRenderResult:
        return self.renderer.render(
            plan,
            model=self._resume_model(checkpoint, fallback_model=model),
            audio_config=audio_config,
            checkpoint=checkpoint,
        )

    @staticmethod
    def _resume_model(
        checkpoint: Mapping[str, Any] | None, *, fallback_model: str
    ) -> str:
        """恢复策略：已完成的历史 checkpoint 按记录的原模型恢复。

        默认模型切换（阶段 1：新任务默认 multilingual）不得重烧已完成的
        历史场景；未完成或无 checkpoint 时按当前请求模型执行。
        """
        if isinstance(checkpoint, Mapping):
            status = str(checkpoint.get("status") or "").strip()
            if status in {"passed", "legacy_stems"}:
                recorded = str(checkpoint.get("model") or "").strip()
                if recorded:
                    return recorded
        return fallback_model

    def _persist_materialized_asset(
        self,
        asset: PreviewReferenceAsset,
        config: Mapping[str, Any],
    ) -> None:
        """回写当前用户已授权私有参考资产的本地物化结果。

        尽力而为：未注入会话工厂时跳过；任何数据库异常都不阻断渲染主流程。
        仓储在此处懒加载，避免场景引擎包在无数据库环境下强制依赖 ORM。
        """
        if self.db_session_factory is None:
            return
        # 懒加载：仅在真正需要落库时引入数据库依赖。
        reference_source = str(config.get("reference_source") or "").strip().lower()
        if reference_source != "user_private":
            return
        reference_asset_id = str(config.get("voice_reference_asset_id") or "").strip()
        owner_user_id = config.get("voice_reference_owner_user_id")
        if not reference_asset_id or owner_user_id in (None, ""):
            logger.warning("私有参考音色缺少后端授权身份，跳过物化结果回写")
            return

        from app.services.audiobook.voice_reference_asset_repository import (
            get_active_voice_reference_asset,
        )

        session = None
        try:
            session = self.db_session_factory()
            persisted = get_active_voice_reference_asset(
                session,
                asset_id=reference_asset_id,
                owner_user_id=int(owner_user_id),
            )
            if persisted is None:
                raise ValueError("private voice reference asset is no longer active")
            persisted.storage_uri = str(asset.storage_path)
            persisted.source_url = asset.source_url or persisted.source_url
            persisted.source_preview_cache_key = asset.source_preview_cache_key
            persisted.sha256 = asset.sha256
            persisted.duration_s = asset.duration_s
            persisted.content_type = asset.content_type
            persisted.reference_field = "audio_data"
            persisted.metadata_json = {
                **dict(persisted.metadata_json or {}),
                "materialized_for_seed_audio": True,
            }
            session.commit()
        except Exception:  # pragma: no cover - 落库失败不影响渲染
            logger.warning("persist materialized reference asset failed", exc_info=True)
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    pass
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    @staticmethod
    def _speaker_names(segments: Sequence[Any]) -> Tuple[str, ...]:
        names = []
        for segment in segments:
            name = str(getattr(segment, "speaker", "") or "旁白").strip() or "旁白"
            if name not in names:
                names.append(name)
        return tuple(names)

    @staticmethod
    def _checkpoint_for(
        checkpoints: Mapping[str, Mapping[str, Any]] | None,
        scene_id: str,
    ) -> Mapping[str, Any] | None:
        if not checkpoints:
            return None
        value = checkpoints.get(scene_id)
        return value if isinstance(value, Mapping) else None

    @staticmethod
    def _materialization_key(
        config: Mapping[str, Any],
        reference: Mapping[str, Any],
    ) -> str:
        identity = {
            "tts_model": str(config.get("tts_model") or ""),
            "voice_id": str(config.get("voice_id") or ""),
            "reference": dict(reference),
        }
        payload = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _materialization_config(
        config: Mapping[str, Any],
        reference: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = dict(config)
        if reference.get("audio_url"):
            result["preview_audio_url"] = reference["audio_url"]
        elif reference.get("audio_data"):
            result["preview_audio_data"] = reference["audio_data"]
        elif reference.get(DEFERRED_PREVIEW_REFERENCE_FIELD):
            result["preview_cache_key"] = reference[
                DEFERRED_PREVIEW_REFERENCE_FIELD
            ]
        return result


__all__ = [
    "ChapterScenePipeline",
    "ChapterScenePipelineResult",
    "ChapterSceneRender",
]
