"""Thin AudiobookEngine integration for the Seed Audio scene pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from app.core.env_loader import get_backend_root
from app.services.audiobook.atomic_files import write_bytes_atomic
from app.services.audiobook.duration_estimator import (
    estimate_narration_duration_seconds,
)
from app.services.audiobook.prompt_audio_asr_provider import (
    create_prompt_audio_asr_provider,
    sanitize_asr_audit_metadata,
)
from app.services.audiobook.prompt_audio_asr_pricing import (
    load_prompt_audio_asr_budget_policy,
)
from app.services.audiobook.project_audio_config import get_seed_audio_model
from app.services.audiobook.scene_engine.chapter_pipeline import (
    ChapterScenePipeline,
    ChapterScenePipelineResult,
    ChapterSceneRender,
)
from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceMaterializer,
)
from app.services.audiobook.scene_engine.provider_attempt_ledger import (
    ProviderAttemptLedger,
)
from app.services.audiobook.scene_engine.scene_billing import (
    build_seed_scene_billing_summary,
)
from app.services.audiobook.scene_engine.scene_assembler import (
    SceneAssemblyResult,
    SceneAssemblySubtitleEntry,
    SceneAudioAssembler,
)
from app.services.audiobook.scene_engine.scene_renderer import (
    DEFAULT_SEED_AUDIO_MODEL,
    SceneRenderService,
)
from app.services.audiobook.task_tracker import StageType
from app.services.audiobook.engine_pkg._tts_mixin import aggregate_tts_cost_stats


logger = logging.getLogger(__name__)

try:
    from app.websocket.manager import ws_manager

    WEBSOCKET_AVAILABLE = True
except Exception:  # pragma: no cover - WebSocket is optional for workers.
    ws_manager = None
    WEBSOCKET_AVAILABLE = False


def _resolve_db_session_factory() -> Optional[Callable[[], Any]]:
    """返回默认数据库会话工厂，数据库层不可用时返回 None。

    参考资产落库是尽力而为的旁路，导入失败或无数据库环境时不应阻断章节渲染。
    """
    try:
        from app.db.base import SessionLocal

        return SessionLocal
    except Exception:  # pragma: no cover - DB layer optional in some contexts.
        return None


class SceneRenderMixin:
    """Route explicitly enabled chapters through the shared scene pipeline."""

    async def _try_generate_seed_scene_chapter(
        self,
        *,
        script_segments: Sequence[Any],
        chapter_id: int,
        task_id: str,
        output_path: Optional[str],
        output_format: str,
        resume_checkpoint: Optional[Dict[str, Any]] = None,
        enable_quality_review: bool = True,
        script_quality_report: Any = None,
        tts_progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        audiobook_project_id: Optional[int] = None,
        pause_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        if str(getattr(self, "_audio_engine_mode", "legacy_stems")) != "seed_scene":
            return None
        if not script_segments:
            raise ValueError("seed_scene requires at least one script segment")

        run_root = (
            get_backend_root()
            / "data"
            / "audiobook_scene_runs"
            / self._safe_scene_path_component(task_id)
            / f"chapter_{int(chapter_id)}"
        )
        run_root.mkdir(parents=True, exist_ok=True)
        checkpoint_value = (resume_checkpoint or {}).get("scene_checkpoints")
        scene_checkpoints = (
            dict(checkpoint_value)
            if isinstance(checkpoint_value, Mapping)
            else {}
        )
        checkpoint_updates = dict(scene_checkpoints)
        seed_audio_model = get_seed_audio_model(
            {"seed_audio_model": getattr(self, "_seed_audio_model", "")}
        )
        event_loop = asyncio.get_running_loop()
        event_loop_thread_id = threading.get_ident()
        pending_progress_tasks: list[asyncio.Task[None]] = []

        async def dispatch_progress(
            payload: Dict[str, Any],
            websocket_payload: Dict[str, Any],
        ) -> None:
            if tts_progress_callback and payload:
                tts_progress_callback(payload)

            if WEBSOCKET_AVAILABLE and ws_manager and audiobook_project_id:
                try:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        **websocket_payload,
                    )
                except Exception as exc:  # pragma: no cover - optional telemetry.
                    logger.warning(
                        "Seed Audio 场景进度推送失败: chapter=%s error=%s",
                        chapter_id,
                        exc,
                    )

        def persist_scene_checkpoints(
            snapshot: Dict[str, Any],
            current_checkpoint: Dict[str, Any],
        ) -> None:
            websocket_enabled = bool(
                WEBSOCKET_AVAILABLE and ws_manager and audiobook_project_id
            )
            if not tts_progress_callback and not websocket_enabled:
                return
            completed_segment_indices = sorted(
                {
                    int(index)
                    for checkpoint in snapshot.values()
                    if isinstance(checkpoint, Mapping)
                    and checkpoint.get("status") == "passed"
                    for index in checkpoint.get("source_segment_indices") or []
                    if isinstance(index, int)
                    and 0 <= index < len(script_segments)
                }
            )
            processed_segment_indices = sorted(
                {
                    int(index)
                    for checkpoint in snapshot.values()
                    if isinstance(checkpoint, Mapping)
                    and checkpoint.get("status") in {"passed", "legacy_stems"}
                    for index in checkpoint.get("source_segment_indices") or []
                    if isinstance(index, int)
                    and 0 <= index < len(script_segments)
                }
            )
            payload = {
                "task_id": task_id,
                "total_segments": len(script_segments),
                "completed_segment_indices": completed_segment_indices,
                "scene_checkpoints": dict(snapshot),
            }
            progress = int(
                round(
                    100 * len(processed_segment_indices) / len(script_segments)
                )
            )
            scene_id = str(current_checkpoint.get("scene_id") or "").strip()
            scene_status = str(current_checkpoint.get("status") or "").strip()
            websocket_payload = {
                "stage": "scene_rendering",
                "progress": max(0, min(progress, 100)),
                "message": f"场景音频处理完成：{scene_id}",
                "stage_metrics": {
                    "scene_id": scene_id,
                    "scene_status": scene_status,
                    "fallback_reason": current_checkpoint.get("fallback_reason"),
                    "processed_segment_count": len(processed_segment_indices),
                    "completed_segment_count": len(completed_segment_indices),
                    "total_segment_count": len(script_segments),
                },
            }
            if threading.get_ident() == event_loop_thread_id:
                if tts_progress_callback:
                    tts_progress_callback(payload)
                if websocket_enabled:
                    pending_progress_tasks.append(
                        event_loop.create_task(
                            dispatch_progress({}, websocket_payload)
                        )
                    )
                return
            future = asyncio.run_coroutine_threadsafe(
                dispatch_progress(payload, websocket_payload),
                event_loop,
            )
            future.result()

        pipeline = self._create_chapter_scene_pipeline(
            run_root=run_root,
            checkpoint_updates=checkpoint_updates,
            checkpoint_persist_callback=persist_scene_checkpoints,
            model=seed_audio_model,
        )

        self.task_tracker.start_stage(task_id, StageType.TTS_SYNTHESIS)
        if WEBSOCKET_AVAILABLE and ws_manager and audiobook_project_id:
            try:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage="scene_rendering",
                    progress=0,
                    message="正在生成场景音频...",
                    stage_metrics={
                        "resumed_scene_count": len(scene_checkpoints),
                        "total_segment_count": len(script_segments),
                    },
                )
            except Exception as exc:  # pragma: no cover - optional telemetry.
                logger.warning(
                    "Seed Audio 场景开始进度推送失败: chapter=%s error=%s",
                    chapter_id,
                    exc,
                )
        pipeline_result = await asyncio.to_thread(
            pipeline.render,
            script_segments,
            voice_mapping=dict(getattr(self, "_scene_voice_mapping", {}) or {}),
            model=seed_audio_model,
            checkpoints=scene_checkpoints,
        )
        if pending_progress_tasks:
            progress_results = await asyncio.gather(
                *pending_progress_tasks,
                return_exceptions=True,
            )
            for progress_result in progress_results:
                if isinstance(progress_result, BaseException):
                    logger.warning(
                        "Seed Audio 场景进度任务执行失败: chapter=%s error=%s",
                        chapter_id,
                        progress_result,
                    )
        fallback_scenes = tuple(
            scene
            for scene in pipeline_result.scenes
            if scene.result.status == "legacy_stems"
        )
        fallback_audio_paths = {}
        fallback_tts_cost_before = float(
            aggregate_tts_cost_stats(
                self.tts_engine,
                getattr(self, "_tts_engines_by_model", None),
            ).get("estimated_cost_yuan")
            or 0.0
        )
        fallback_output_root = run_root / "legacy_fallbacks"
        fallback_output_root.mkdir(parents=True, exist_ok=True)
        for scene in fallback_scenes:
            scene_id = scene.plan.scene_id
            fallback_path = self._reusable_legacy_fallback_path(
                checkpoint_updates.get(scene_id),
                scene.plan,
            )
            if fallback_path is None:
                fallback_path = await self._render_legacy_scene_fallback(
                    scene,
                    script_segments,
                    fallback_output_root,
                    pause_check=pause_check,
                )
                updated_checkpoint = self._checkpoint_with_fallback_artifact(
                    checkpoint_updates.get(scene_id),
                    scene,
                    fallback_path,
                )
                checkpoint_updates[scene_id] = updated_checkpoint
                persist_scene_checkpoints(
                    dict(checkpoint_updates),
                    dict(updated_checkpoint),
                )
            fallback_audio_paths[scene_id] = fallback_path

        scene_metrics = self._scene_render_metrics(pipeline_result)
        scene_metrics["local_fallback_count"] = len(fallback_audio_paths)
        provider_attempt_ledger = getattr(pipeline, "provider_attempt_ledger", None)
        provider_attempts = (
            provider_attempt_ledger.records()
            if provider_attempt_ledger is not None
            and callable(getattr(provider_attempt_ledger, "records", None))
            else None
        )
        scene_billing = build_seed_scene_billing_summary(
            checkpoint_updates,
            provider_attempts=provider_attempts,
            model=seed_audio_model,
        )
        scene_metrics["billing"] = scene_billing
        self.task_tracker.complete_stage(
            task_id,
            StageType.TTS_SYNTHESIS,
            metrics=scene_metrics,
        )

        self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
        target_path = Path(output_path) if output_path else (
            run_root / f"chapter.{self._normalized_scene_output_format(output_format)}"
        )
        assembler = self._create_scene_audio_assembler()
        assembly = await asyncio.to_thread(
            assembler.assemble,
            pipeline_result.scenes,
            output_path=target_path,
            output_format=output_format,
            fallback_audio_paths=fallback_audio_paths,
        )
        audio_data = assembly.audio_path.read_bytes()
        if output_path is None:
            staging_path = Path(assembly.audio_path).resolve(strict=False)
            try:
                staging_path.relative_to(run_root.resolve(strict=False))
            except ValueError:
                logger.warning(
                    "Seed Scene staging path escaped run root; skip cleanup: path=%s root=%s",
                    staging_path,
                    run_root,
                )
            else:
                try:
                    staging_path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning(
                        "Seed Scene staging audio cleanup failed: path=%s error=%s",
                        staging_path,
                        exc,
                    )
        audio_info = {
            "duration_seconds": assembly.duration_s,
            "file_size": len(audio_data),
            "format": assembly.output_format,
            "scene_count": len(assembly.scene_timings),
            "loudness_normalized": assembly.loudness_normalized,
            "loudness_report": dict(assembly.loudness_report or {}),
        }
        self.task_tracker.complete_stage(
            task_id,
            StageType.AUDIO_MIXING,
            metrics={
                "audio_info": audio_info,
                "scene_timing_count": len(assembly.scene_timings),
            },
        )

        self.task_tracker.start_stage(task_id, StageType.FINAL_AUDIO_REVIEW)
        if enable_quality_review and callable(getattr(self, "_final_audio_review", None)):
            segment_audio_presence = [False] * len(script_segments)
            for scene in pipeline_result.scenes:
                has_scene_audio = bool(
                    (
                        scene.result.audio_path
                        and scene.result.audio_path.exists()
                    )
                    or fallback_audio_paths.get(scene.plan.scene_id)
                )
                if not has_scene_audio:
                    continue
                for source_index in scene.plan.source_segment_indices:
                    if 0 <= source_index < len(segment_audio_presence):
                        segment_audio_presence[source_index] = True
            final_audio_review = self._final_audio_review(
                audio_info=audio_info,
                file_size=len(audio_data),
                script_quality_report=script_quality_report,
                audio_data=audio_data,
                script_segments=script_segments,
                audio_list=None,
                audio_presence=segment_audio_presence,
            )
        else:
            final_audio_review = {"skipped": True}
        self.task_tracker.complete_stage(
            task_id,
            StageType.FINAL_AUDIO_REVIEW,
            metrics=final_audio_review,
        )
        self.task_tracker.complete_task(task_id)

        timing_segments_payload, segment_timings = self._assembly_subtitle_payload(
            pipeline_result,
            assembly,
        )
        dialogue_count = sum(
            1 for segment in script_segments if getattr(segment, "type", "") == "dialogue"
        )
        narration_count = sum(
            1 for segment in script_segments if getattr(segment, "type", "") == "narration"
        )
        tts_stats = aggregate_tts_cost_stats(
            self.tts_engine,
            getattr(self, "_tts_engines_by_model", None),
        )
        tts_stats["scene_billing"] = scene_billing
        actual_cost_yuan = scene_billing.get("actual_cost_yuan")
        if actual_cost_yuan is not None:
            fallback_tts_cost = max(
                float(tts_stats.get("estimated_cost_yuan") or 0.0)
                - fallback_tts_cost_before,
                0.0,
            )
            total_cost = float(actual_cost_yuan) + fallback_tts_cost
            tts_stats["cost_components"] = {
                "seed_audio_yuan": round(float(actual_cost_yuan), 4),
                "legacy_fallback_tts_yuan": round(fallback_tts_cost, 4),
                "total_yuan": round(total_cost, 4),
            }
            tts_stats["estimated_cost_yuan"] = round(total_cost, 4)
            tts_stats["estimated_cost"] = f"¥{total_cost:.4f}"
        return {
            "success": True,
            "task_id": task_id,
            "audio_data": audio_data,
            "duration": assembly.duration_s,
            "file_size": len(audio_data),
            "segment_timings": segment_timings,
            "timing_segments_payload": timing_segments_payload,
            "script_segments_payload": [
                self._serialize_scene_segment(segment)
                for segment in script_segments
            ],
            "scene_checkpoints": checkpoint_updates,
            "scene_render": scene_metrics,
            "stats": {
                "mode": "seed_scene",
                "parse_stats": {
                    "total_segments": len(script_segments),
                    "dialogue_count": dialogue_count,
                    "narration_count": narration_count,
                },
                "script_segments": len(script_segments),
                "tts_stats": tts_stats,
                "audio_info": audio_info,
                "scene_render": scene_metrics,
                "scene_billing": scene_billing,
                "final_audio_review": final_audio_review,
            },
        }

    def _create_chapter_scene_pipeline(
        self,
        *,
        run_root: Path,
        checkpoint_updates: Dict[str, Any],
        checkpoint_persist_callback: Optional[
            Callable[[Dict[str, Any], Dict[str, Any]], None]
        ] = None,
        model: str = DEFAULT_SEED_AUDIO_MODEL,
    ) -> ChapterScenePipeline:
        from adapters.registry import registry

        adapter = registry.get_adapter(model)
        if adapter is None:
            raise RuntimeError("Seed Audio adapter is unavailable")

        def write_checkpoint(payload: Dict[str, Any]) -> None:
            scene_id = str(payload.get("scene_id") or "").strip()
            if scene_id:
                checkpoint_updates[scene_id] = dict(payload)
                if checkpoint_persist_callback:
                    checkpoint_persist_callback(
                        dict(checkpoint_updates),
                        dict(payload),
                    )

        provider_attempt_ledger = ProviderAttemptLedger(
            run_root / "provider_attempts.jsonl"
        )
        asr_budget_policy = load_prompt_audio_asr_budget_policy()
        configured_asr_provider = create_prompt_audio_asr_provider()

        def transcribe_scene_audio(
            audio_path: Path,
            *,
            audio_url: Optional[str] = None,
        ) -> Dict[str, Any]:
            if configured_asr_provider is None:
                return {}
            result = (
                configured_asr_provider.transcribe(
                    str(audio_path),
                    audio_url=audio_url,
                )
                if audio_url
                else configured_asr_provider.transcribe(str(audio_path))
            )
            transcription = {
                "transcript": str(
                    getattr(result, "transcript", "") or ""
                ).strip(),
                "subtitle_payload": getattr(result, "subtitle_payload", None),
                "provider": str(getattr(result, "provider", "") or "").strip(),
                "model": str(getattr(result, "model", "") or "").strip(),
            }
            audit_metadata = sanitize_asr_audit_metadata(
                getattr(result, "metadata", None)
            )
            if audit_metadata:
                transcription["metadata"] = audit_metadata
            return transcription

        transcribe_scene_audio.supports_timestamps = bool(
            getattr(configured_asr_provider, "supports_timestamps", False)
        )
        transcribe_scene_audio.provider_name = str(
            getattr(configured_asr_provider, "name", "") or ""
        ).strip()
        transcribe_scene_audio.model = str(
            getattr(configured_asr_provider, "model", "") or ""
        ).strip()

        renderer = SceneRenderService(
            adapter=adapter,
            output_root=run_root / "renders",
            checkpoint_writer=write_checkpoint,
            provider_attempt_recorder=provider_attempt_ledger.record,
            asr_provider=(
                transcribe_scene_audio
                if configured_asr_provider is not None
                else None
            ),
            max_asr_attempts_per_scene=asr_budget_policy.max_attempts_per_scene,
            max_asr_cost_yuan_per_scene=asr_budget_policy.max_cost_yuan_per_scene,
        )
        return ChapterScenePipeline(
            reference_materializer=PreviewReferenceMaterializer(
                output_root=run_root / "references"
            ),
            renderer=renderer,
            provider_attempt_ledger=provider_attempt_ledger,
            db_session_factory=_resolve_db_session_factory(),
        )

    @staticmethod
    def _create_scene_audio_assembler() -> SceneAudioAssembler:
        return SceneAudioAssembler()

    async def _render_legacy_scene_fallback(
        self,
        scene: ChapterSceneRender,
        script_segments: Sequence[Any],
        output_root: Path,
        pause_check: Optional[Callable[[], bool]] = None,
    ) -> Path:
        selected_segments = [
            script_segments[index]
            for index in scene.plan.source_segment_indices
        ]
        synthesis = await self._synthesize_segments_with_resume(
            selected_segments,
            resume_checkpoint=None,
            pause_check=pause_check,
        )
        audio_list = list(synthesis.get("audio_list") or [])
        if not any(audio_list):
            raise RuntimeError(
                f"legacy_scene_fallback_empty:{scene.plan.scene_id}"
            )
        segment_types = self._build_mixer_segment_types(selected_segments)
        build_pause_after_ms = getattr(self, "_build_mixer_pause_after_ms", None)
        pause_after_ms = (
            build_pause_after_ms(selected_segments)
            if callable(build_pause_after_ms)
            else [None] * len(audio_list)
        )
        build_segment_timeline = getattr(
            self.audio_mixer,
            "build_segment_timeline",
            None,
        )
        segment_timings = []
        if callable(build_segment_timeline):
            try:
                segment_timings = build_segment_timeline(
                    audio_list,
                    segment_types=segment_types,
                    pause_after_ms=pause_after_ms,
                )
            except TypeError:
                segment_timings = build_segment_timeline(
                    audio_list,
                    segment_types=segment_types,
                )
        try:
            audio_data = self.audio_mixer.mix_chapter(
                audio_list,
                output_format="mp3",
                segment_types=segment_types,
                pause_after_ms=pause_after_ms,
            )
        except TypeError:
            audio_data = self.audio_mixer.mix_chapter(
                audio_list,
                segment_types=segment_types,
            )
        if not audio_data:
            raise RuntimeError(
                f"legacy_scene_fallback_empty:{scene.plan.scene_id}"
            )

        fallback_duration_s = self._legacy_fallback_duration_seconds(
            audio_data,
            segment_timings,
        )
        effect_timeline = self._build_legacy_scene_timeline(
            getattr(self, "_last_effect_timeline", None),
            script_segments=script_segments,
            source_segment_indices=scene.plan.source_segment_indices,
            segment_timings=segment_timings,
            total_duration_s=fallback_duration_s,
            align_environment=True,
        )
        apply_sound_effects = getattr(self, "_apply_sound_effects", None)
        if effect_timeline and callable(apply_sound_effects):
            audio_data = apply_sound_effects(audio_data, effect_timeline)

        music_timeline = self._build_legacy_scene_timeline(
            getattr(self, "_last_music_timeline", None),
            script_segments=script_segments,
            source_segment_indices=scene.plan.source_segment_indices,
            segment_timings=segment_timings,
            total_duration_s=fallback_duration_s,
            align_environment=False,
        )
        apply_background_music = getattr(self, "_apply_background_music", None)
        if music_timeline and callable(apply_background_music):
            audio_data = apply_background_music(audio_data, music_timeline)

        output_root.mkdir(parents=True, exist_ok=True)
        target = output_root / f"{self._safe_scene_path_component(scene.plan.scene_id)}.mp3"
        write_bytes_atomic(target, audio_data)
        return target

    @classmethod
    def _reusable_legacy_fallback_path(
        cls,
        checkpoint: Any,
        plan: Any,
    ) -> Optional[Path]:
        if not isinstance(checkpoint, Mapping):
            return None
        artifact = checkpoint.get("fallback_artifact")
        if not isinstance(artifact, Mapping):
            return None
        if artifact.get("prompt_hash") != plan.prompt_hash:
            return None
        if artifact.get("quality_policy_hash") != plan.quality_policy_hash:
            return None
        if tuple(artifact.get("reference_hashes") or ()) != tuple(plan.reference_hashes):
            return None
        if tuple(artifact.get("source_segment_indices") or ()) != tuple(
            plan.source_segment_indices
        ):
            return None
        expected_text_hash = hashlib.sha256(
            plan.expected_text.encode("utf-8")
        ).hexdigest()
        if artifact.get("source_text_hash") != expected_text_hash:
            return None
        path = Path(str(artifact.get("audio_path") or ""))
        if not path.exists() or not path.is_file():
            return None
        try:
            expected_size = int(artifact.get("file_size") or 0)
        except (TypeError, ValueError):
            return None
        if expected_size <= 0 or path.stat().st_size != expected_size:
            return None
        if str(artifact.get("audio_sha256") or "") != cls._file_sha256(path):
            return None
        return path

    @classmethod
    def _checkpoint_with_fallback_artifact(
        cls,
        checkpoint: Any,
        scene: ChapterSceneRender,
        audio_path: Path,
    ) -> Dict[str, Any]:
        path = Path(audio_path)
        plan = scene.plan
        updated = dict(checkpoint) if isinstance(checkpoint, Mapping) else {}
        updated.update(
            {
                "scene_id": plan.scene_id,
                "source_segment_indices": list(plan.source_segment_indices),
                "source_text_hash": hashlib.sha256(
                    plan.expected_text.encode("utf-8")
                ).hexdigest(),
                "status": "legacy_stems",
                "action": "legacy_stems",
                "prompt_hash": plan.prompt_hash,
                "quality_policy_hash": plan.quality_policy_hash,
                "reference_hashes": list(plan.reference_hashes),
                "fallback_reason": scene.result.fallback_reason,
                "fallback_status": "ready",
                "fallback_artifact": {
                    "audio_path": str(path),
                    "audio_sha256": cls._file_sha256(path),
                    "file_size": path.stat().st_size,
                    "source_segment_indices": list(plan.source_segment_indices),
                    "source_text_hash": hashlib.sha256(
                        plan.expected_text.encode("utf-8")
                    ).hexdigest(),
                    "prompt_hash": plan.prompt_hash,
                    "quality_policy_hash": plan.quality_policy_hash,
                    "reference_hashes": list(plan.reference_hashes),
                },
            }
        )
        return updated

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as audio_file:
            for chunk in iter(lambda: audio_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _legacy_fallback_duration_seconds(
        self,
        audio_data: bytes,
        segment_timings: Sequence[Mapping[str, Any]],
    ) -> float:
        timing_end = max(
            (
                float(timing.get("end") or 0.0)
                for timing in segment_timings
                if isinstance(timing, Mapping)
            ),
            default=0.0,
        )
        if timing_end > 0:
            return timing_end
        get_audio_info = getattr(self.audio_mixer, "get_audio_info", None)
        if not callable(get_audio_info):
            return 0.0
        try:
            return max(
                0.0,
                float((get_audio_info(audio_data) or {}).get("duration_seconds") or 0.0),
            )
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _timeline_source_segment_index(scene_id: Any) -> Optional[int]:
        value = str(scene_id or "").strip()
        for prefix in ("scene_", "climax_", "shift_"):
            if value.startswith(prefix):
                try:
                    return int(value[len(prefix):])
                except ValueError:
                    return None
        return None

    def _build_legacy_scene_timeline(
        self,
        timeline: Any,
        *,
        script_segments: Sequence[Any],
        source_segment_indices: Sequence[int],
        segment_timings: Sequence[Mapping[str, Any]],
        total_duration_s: float,
        align_environment: bool,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(timeline, Mapping):
            return None
        timeline_items = timeline.get("timeline")
        if not isinstance(timeline_items, Sequence) or isinstance(
            timeline_items,
            (str, bytes),
        ):
            return None

        estimated_starts = []
        estimated_cursor = 0.0
        for segment in script_segments:
            estimated_starts.append(estimated_cursor)
            estimated_cursor += max(
                0.0,
                estimate_narration_duration_seconds(
                    str(getattr(segment, "text", "") or "")
                ),
            )

        local_timings: Dict[int, Dict[str, float]] = {}
        normalized_indices = tuple(int(index) for index in source_segment_indices)
        for timing in segment_timings:
            if not isinstance(timing, Mapping):
                continue
            try:
                local_index = int(timing.get("index"))
                source_index = normalized_indices[local_index]
                start = max(0.0, float(timing.get("start") or 0.0))
                duration = max(0.0, float(timing.get("duration") or 0.0))
            except (IndexError, TypeError, ValueError):
                continue
            local_timings[source_index] = {
                "start": start,
                "duration": duration,
            }

        safe_total_duration = max(0.0, float(total_duration_s or 0.0))
        adjusted_items = []
        for item in timeline_items:
            if not isinstance(item, Mapping):
                continue
            source_index = self._timeline_source_segment_index(item.get("scene_id"))
            local_timing = local_timings.get(source_index) if source_index is not None else None
            if local_timing is None or source_index >= len(estimated_starts):
                continue
            try:
                original_timestamp = max(0.0, float(item.get("timestamp") or 0.0))
            except (TypeError, ValueError):
                continue

            relative_timestamp = max(
                0.0,
                original_timestamp - estimated_starts[source_index],
            )
            relative_timestamp = min(relative_timestamp, local_timing["duration"])
            local_timestamp = min(
                safe_total_duration,
                local_timing["start"] + relative_timestamp,
            )
            adjusted = dict(item)
            adjusted["timestamp"] = local_timestamp
            if item.get("duration") is not None:
                try:
                    duration = max(0.0, float(item.get("duration") or 0.0))
                except (TypeError, ValueError):
                    duration = 0.0
                adjusted["duration"] = min(
                    duration,
                    max(0.0, safe_total_duration - local_timestamp),
                )
            adjusted_items.append(adjusted)

        adjusted_items.sort(key=lambda item: float(item.get("timestamp") or 0.0))
        if align_environment:
            environment_indices = [
                index
                for index, item in enumerate(adjusted_items)
                if item.get("type") == "environment" or item.get("loop")
            ]
            for position, item_index in enumerate(environment_indices):
                item = adjusted_items[item_index]
                start = float(item.get("timestamp") or 0.0)
                next_start = safe_total_duration
                if position + 1 < len(environment_indices):
                    next_start = float(
                        adjusted_items[environment_indices[position + 1]].get(
                            "timestamp"
                        )
                        or safe_total_duration
                    )
                item["duration"] = max(0.0, next_start - start)
                item["loop"] = True

        if not adjusted_items:
            return None
        local_timeline = dict(timeline)
        local_timeline["timeline"] = adjusted_items
        if "total_effects" in local_timeline:
            local_timeline["total_effects"] = len(adjusted_items)
        if "total_cues" in local_timeline:
            local_timeline["total_cues"] = len(adjusted_items)
        return local_timeline

    @staticmethod
    def _scene_render_metrics(
        pipeline_result: ChapterScenePipelineResult,
    ) -> Dict[str, Any]:
        scenes = [
            {
                "scene_id": scene.plan.scene_id,
                "source_segment_indices": list(scene.plan.source_segment_indices),
                "status": scene.result.status,
                "attempts": scene.result.attempts,
                "reused_checkpoint": scene.result.reused_checkpoint,
                "fallback_reason": scene.result.fallback_reason,
                "metadata": dict(scene.result.metadata or {}),
            }
            for scene in pipeline_result.scenes
        ]
        return {
            "scene_count": len(scenes),
            "passed_scene_count": sum(
                1 for scene in pipeline_result.scenes if scene.result.status == "passed"
            ),
            "fallback_scene_count": sum(
                1
                for scene in pipeline_result.scenes
                if scene.result.status == "legacy_stems"
            ),
            "reused_scene_count": sum(
                1 for scene in pipeline_result.scenes if scene.result.reused_checkpoint
            ),
            "scenes": scenes,
        }

    @staticmethod
    def _assembly_subtitle_payload(
        pipeline_result: ChapterScenePipelineResult,
        assembly: SceneAssemblyResult,
    ) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
        subtitle_entries = list(assembly.subtitle_entries)
        covered_scene_ids = {entry.scene_id for entry in subtitle_entries}
        timing_by_scene = {
            timing.scene_id: timing
            for timing in assembly.scene_timings
        }
        for scene in pipeline_result.scenes:
            if scene.plan.scene_id in covered_scene_ids:
                continue
            timing = timing_by_scene.get(scene.plan.scene_id)
            if timing is None or not scene.plan.expected_text.strip():
                continue
            subtitle_entries.append(
                SceneAssemblySubtitleEntry(
                    index=len(subtitle_entries) + 1,
                    scene_id=scene.plan.scene_id,
                    start_s=timing.start_s,
                    end_s=timing.end_s,
                    text=scene.plan.expected_text,
                    speaker=(
                        scene.plan.speaker_names[0]
                        if len(scene.plan.speaker_names) == 1
                        else None
                    ),
                )
            )
        subtitle_entries.sort(key=lambda entry: (entry.start_s, entry.end_s))
        payload = []
        timings = []
        for index, entry in enumerate(subtitle_entries):
            payload.append(
                {
                    "text": entry.text,
                    "speaker": entry.speaker,
                    "emotion": entry.emotion,
                }
            )
            timings.append(
                {
                    "index": index,
                    "start": round(float(entry.start_s), 6),
                    "end": round(float(entry.end_s), 6),
                    "duration": round(float(entry.end_s - entry.start_s), 6),
                }
            )
        return payload, timings

    @staticmethod
    def _serialize_scene_segment(segment: Any) -> Dict[str, Any]:
        if is_dataclass(segment):
            return asdict(segment)
        if isinstance(segment, Mapping):
            return dict(segment)
        return dict(getattr(segment, "__dict__", {}) or {})

    @staticmethod
    def _safe_scene_path_component(value: str) -> str:
        return "".join(
            character if character.isalnum() or character in "._-" else "-"
            for character in str(value or "")
        ).strip(".-") or "scene-run"

    @staticmethod
    def _normalized_scene_output_format(value: str) -> str:
        normalized = str(value or "mp3").strip().lower().lstrip(".")
        return "m4b" if normalized == "m4a" else normalized


__all__ = ["SceneRenderMixin"]
