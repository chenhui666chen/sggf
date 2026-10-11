"""
Celery 主任务
"""
import json
import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db.base import SessionLocal
from app.models.project import Project
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION
from app.utils.datetime_utils import utc_now
from app.services.dreamweaver.events import DreamweaverEventEmitter
from app.services.dreamweaver.library import required_library_roles
from app.services.dreamweaver.task_trace import build_dreamweaver_trace_context
from app.services.user_center_points_events import (
    record_dreamweaver_billing_freeze,
    record_dreamweaver_billing_release,
    record_dreamweaver_billing_settle,
)
from pipeline.state_machine import RunContext, State, progress_percent, stage_label, step

from ._env import _env_int, _env_float, _safe_int_list, _safe_str_list
from ._asset_plan import (
    _estimate_pipeline_max_steps,
    _build_asset_plan_from_storyboard,
    _build_asset_library_plan_from_payload,
)
from ._events import _emit_asset_ready_events
from ._resume import _build_source_text, _resume_payload_from_contract, _apply_restart_reset
from ._artifacts import _stage_artifacts, _artifact_summary
from ._db import _update_generation_history

logger = logging.getLogger(__name__)


@celery_app.task(name="dreamweaver.run", bind=True)
def run_dreamweaver_task(
    self,
    task_id: str,
    run_id: str,
    project_id: int,
    *args: Any,
) -> None:
    """
    Run DreamWeaver pipeline asynchronously and persist the result into generation_history.
    """
    from app.services.dreamweaver.persistence import build_contract_from_payload, persist_contract

    session = SessionLocal()
    emitter: DreamweaverEventEmitter | None = None
    try:
        resume_config: Dict[str, Any] | None = None
        runtime_config: Dict[str, Any] | None = None
        args_list = list(args)
        if args_list and isinstance(args_list[-1], dict) and bool(args_list[-1].get("resume")):
            resume_config = args_list.pop()
        if args_list and isinstance(args_list[-1], dict):
            runtime_config = args_list.pop()
        args = tuple(args_list)

        # 兼容旧任务参数格式：(task_id, run_id, project_id, chapter_ids, source_text)
        # 新任务参数格式：(task_id, run_id, project_id, user_id, chapter_ids, source_text, schema_version?, runtime_config?)
        if len(args) == 2:
            chapter_ids, source_text = args
            user_id = None
            schema_version = None
        elif len(args) == 3:
            # (chapter_ids, source_text, schema_version) or (user_id, chapter_ids, source_text)
            if isinstance(args[0], int):
                user_id, chapter_ids, source_text = args
                schema_version = None
            else:
                chapter_ids, source_text, schema_version = args
                user_id = None
        elif len(args) == 4:
            # (user_id, chapter_ids, source_text, schema_version)
            user_id, chapter_ids, source_text, schema_version = args
        else:
            raise TypeError(f"unexpected args length: {len(args)}")

        schema_version_effective = (
            schema_version if isinstance(schema_version, str) and schema_version else DREAMWEAVER_SCHEMA_VERSION
        )

        if user_id is None:
            project = session.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise RuntimeError("project not found for legacy task args")
            user_id = int(project.user_id)

        chapter_ids = _safe_int_list(chapter_ids)
        source_text = str(source_text or "")

        payload: Dict[str, Any]
        if isinstance(resume_config, dict) and bool(resume_config.get("resume")):
            from app.models.dreamweaver import DreamweaverProject as DreamweaverProjectModel

            row = (
                session.query(DreamweaverProjectModel)
                .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == user_id)
                .first()
            )
            if not row or not isinstance(row.contract_json, dict):
                raise RuntimeError("resume requires persisted contract_json")

            contract = row.contract_json
            payload = _resume_payload_from_contract(
                contract,
                project_id=project_id,
                schema_version=schema_version_effective,
                fallback_chapter_ids=chapter_ids,
                fallback_source_text=source_text,
            )
        else:
            payload = {
                "project_id": project_id,
                "chapter_ids": chapter_ids,
                "source_text": source_text,
                "schema_version": schema_version_effective,
            }
        if isinstance(runtime_config, dict):
            if isinstance(runtime_config.get("image_config"), dict):
                payload["image_config"] = runtime_config["image_config"]
            if isinstance(runtime_config.get("qc_config"), dict):
                payload["qc_config"] = runtime_config["qc_config"]
            if isinstance(runtime_config.get("video_config"), dict):
                payload["video_config"] = runtime_config["video_config"]
            if isinstance(runtime_config.get("preflight"), dict):
                payload["preflight"] = runtime_config.get("preflight")
            if isinstance(runtime_config.get("quality_mode"), str) and runtime_config["quality_mode"].strip():
                payload["quality_mode"] = runtime_config["quality_mode"].strip().lower()
            if isinstance(runtime_config.get("smart_tuning"), bool):
                payload["smart_tuning"] = runtime_config.get("smart_tuning")
            if isinstance(runtime_config.get("smart_tuning_snapshot"), dict):
                payload["smart_tuning_snapshot"] = runtime_config.get("smart_tuning_snapshot")
            if isinstance(runtime_config.get("style_preset"), str) and runtime_config["style_preset"].strip():
                payload["style_preset"] = runtime_config["style_preset"].strip()
            if isinstance(runtime_config.get("style_prompt"), str) and runtime_config["style_prompt"].strip():
                payload["style_prompt"] = runtime_config["style_prompt"].strip()
            if isinstance(runtime_config.get("prompt_review_required"), bool):
                payload["prompt_review_required"] = runtime_config.get("prompt_review_required")
            if isinstance(runtime_config.get("prompt_review"), dict):
                payload["prompt_review"] = runtime_config.get("prompt_review")

        if isinstance(payload.get("chapter_ids"), list):
            payload["chapter_ids"] = _safe_int_list(payload.get("chapter_ids"))
        else:
            payload["chapter_ids"] = []
        if not isinstance(payload.get("source_text"), str):
            payload["source_text"] = str(payload.get("source_text") or "")

        # 让统计与后续链路使用最终 chapter_ids（resume 时原始 args 可能为空）
        chapter_ids = payload["chapter_ids"]
        source_text = str(payload.get("source_text") or "")

        if isinstance(resume_config, dict) and bool(resume_config.get("resume")):
            start_state_raw = str(resume_config.get("start_state") or "").strip().upper()
            reset_policy = str(resume_config.get("reset_policy") or "none").strip().lower()
            if start_state_raw:
                # 局部重跑仅在 reset_policy=downstream 时生效，避免影响正常 resume
                if reset_policy == "downstream":
                    shot_ids = _safe_str_list(resume_config.get("regenerate_shot_ids"))
                    if shot_ids:
                        payload["regenerate_shot_ids"] = shot_ids
                    else:
                        payload.pop("regenerate_shot_ids", None)

                    cam_idxs = _safe_int_list(resume_config.get("regenerate_cam_idxs"))
                    if cam_idxs:
                        payload["regenerate_cam_idxs"] = cam_idxs[:200]
                    else:
                        payload.pop("regenerate_cam_idxs", None)

                    roles = _safe_str_list(resume_config.get("asset_library_regenerate_roles"))
                    if roles:
                        payload["asset_library_regenerate_roles"] = roles
                    else:
                        payload.pop("asset_library_regenerate_roles", None)

                _apply_restart_reset(payload, start_state=start_state_raw, reset_policy=reset_policy)
                if start_state_raw == "SCRIPT" and not str(payload.get("source_text") or "").strip():
                    payload["source_text"] = _build_source_text(session, project_id=project_id, chapter_ids=payload["chapter_ids"])

        try:
            from app.services.dreamweaver.library import enrich_payload_with_library

            enrich_payload_with_library(
                session,
                payload,
                project_id=project_id,
                user_id=user_id,
                max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
                max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
                max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
            )
        except Exception as e:
            logger.warning("Failed to build library spec for project %s: %s", project_id, e)
        else:
            try:
                spec = payload.get("asset_library_spec")
                if isinstance(spec, dict):
                    allowed_roles = set(required_library_roles(spec))
                    regen_roles = _safe_str_list(payload.get("asset_library_regenerate_roles"))
                    if regen_roles:
                        filtered_roles = [role for role in regen_roles if role in allowed_roles]
                        if filtered_roles:
                            payload["asset_library_regenerate_roles"] = filtered_roles
                        else:
                            payload.pop("asset_library_regenerate_roles", None)
            except Exception as e:
                logger.debug("Failed to filter regenerate roles: %s", e)

        emitter = DreamweaverEventEmitter(project_id=project_id, user_id=user_id, run_id=run_id)
        ctx = RunContext(
            run_id=run_id,
            payload=payload,
            event_emitter=emitter,
        )

        if isinstance(resume_config, dict) and isinstance(resume_config.get("start_state"), str):
            try:
                ctx.state = State[resume_config["start_state"]]
            except Exception as e:  # noqa: BLE001
                logger.debug("Invalid start_state '%s': %s, falling back to INIT", resume_config.get("start_state"), e)
                ctx.state = State.INIT

        queue_name = None
        try:
            delivery = getattr(getattr(self, "request", None), "delivery_info", None)
            if isinstance(delivery, dict) and isinstance(delivery.get("routing_key"), str):
                queue_name = str(delivery.get("routing_key") or "").strip() or None
        except Exception as e:  # noqa: BLE001
            logger.debug("Failed to get queue name from delivery_info: %s", e)
            queue_name = None

        trace_ctx = build_dreamweaver_trace_context(
            trace_id=task_id,
            celery_task_id=task_id,
            project_id=project_id,
            user_id=user_id,
            run_id=run_id,
            stage=stage_label(ctx.state),
            state=ctx.state.name,
            status="running",
            progress=progress_percent(ctx.state),
            queue=queue_name,
            source_chapter_count=len(chapter_ids),
            quality_mode=runtime_config.get("quality_mode") if isinstance(runtime_config, dict) else None,
        )
        logger.info(
            "DreamWeaver run started: trace_id=%s project_id=%s run_id=%s stage=%s state=%s queue=%s",
            trace_ctx.get("trace_id"),
            project_id,
            run_id,
            trace_ctx.get("stage"),
            trace_ctx.get("state"),
            queue_name,
        )

        running_payload = {
            "run_id": run_id,
            "state": ctx.state.name,
            "stage": stage_label(ctx.state),
            "progress": progress_percent(ctx.state),
            "source_chapter_count": len(chapter_ids),
        }
        if queue_name:
            running_payload["queue"] = queue_name
        _update_generation_history(
            task_id,
            status="running",
            result=json.dumps(running_payload, ensure_ascii=False),
            error=None,
        )
        current_stage = stage_label(ctx.state)
        emitter.emit_stage_start(stage=current_stage, state=ctx.state.name, progress=progress_percent(ctx.state))
        emitter.emit_stage_progress(stage=current_stage, state=ctx.state.name, progress=progress_percent(ctx.state))
        asset_plan_emitted = False
        library_plan_emitted = False
        emitted_asset_keys: set[str] = set()
        # 逐步执行并持续刷新 progress/state，便于前端轮询展示。
        max_steps = _estimate_pipeline_max_steps(payload=ctx.payload)
        loop_exhausted = True
        for _ in range(max_steps):
            if ctx.state in (
                State.DONE,
                State.FAILED,
                State.WAITING_SCRIPT_APPROVAL,
                State.WAITING_APPROVAL,
                State.WAITING_VIDEO_CONFIRMATION,
            ):
                loop_exhausted = False
                break
            prev_stage = stage_label(ctx.state)
            prev_state = ctx.state.name
            # STORYBOARD 前：跨板块解析角色参考音频（四轨声音方案 O4，sound_track 决策消费；
            # 无可用资产时 no-op，对白轨自动降级后期 TTS，不阻断管线）
            if ctx.state == State.STORYBOARD and "voice_reference_audio" not in ctx.payload:
                try:
                    from app.services.dreamweaver.voice_reference_bridge import (
                        inject_voice_references_for_storyboard,
                    )

                    inject_voice_references_for_storyboard(
                        session,
                        ctx.payload,
                        run_id=run_id,
                        owner_user_id=user_id,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("Voice reference bridge failed for run %s: %s", run_id, e)
            ctx = step(ctx)
            next_stage = stage_label(ctx.state)
            if next_stage != prev_stage:
                emitter.emit_stage_end(stage=prev_stage, state=prev_state, progress=progress_percent(ctx.state))
                emitter.emit_stage_start(stage=next_stage, state=ctx.state.name, progress=progress_percent(ctx.state))
            emitter.emit_stage_progress(stage=next_stage, state=ctx.state.name, progress=progress_percent(ctx.state))

            if not asset_plan_emitted:
                storyboard = ctx.payload.get("storyboard")
                plan_items = _build_asset_plan_from_storyboard(storyboard)
                if plan_items:
                    emitter.emit_event(
                        stage=next_stage,
                        event_type="asset_plan",
                        payload={"items": plan_items, "total": len(plan_items)},
                    )
                    asset_plan_emitted = True

            if not library_plan_emitted and next_stage in {"asset_library", "waiting_approval"}:
                library_plan = _build_asset_library_plan_from_payload(ctx.payload)
                if library_plan:
                    emitter.emit_event(
                        stage=next_stage,
                        event_type="asset_library_plan",
                        payload={"items": library_plan, "total": len(library_plan)},
                    )
                    library_plan_emitted = True

            _emit_asset_ready_events(
                emitter,
                payload=ctx.payload,
                stage=next_stage,
                emitted_keys=emitted_asset_keys,
            )

            # 将剧本阶段抽取到的实体同步回项目，并刷新素材库 spec
            try:
                entities = ctx.payload.get("script_entities")
                if isinstance(entities, dict) and not bool(ctx.payload.get("script_entities_synced")):
                    has_any = any(
                        isinstance(entities.get(k), list) and bool(entities.get(k))
                        for k in ("characters", "scenes", "props")
                    )
                    if not has_any:
                        ctx.payload["script_entities_synced"] = True
                    else:
                        from app.services.dreamweaver.script_entities import sync_script_entities_to_project

                        sync_result = sync_script_entities_to_project(
                            session,
                            project_id=project_id,
                            entities=entities,
                        )
                        ctx.payload["script_entities_synced"] = True
                        ctx.payload["script_entities_sync"] = sync_result
                        profiles = ctx.payload.get("character_profiles")
                        if isinstance(profiles, list):
                            entity_chars = entities.get("characters") if isinstance(entities.get("characters"), list) else []
                            id_by_name: Dict[str, str] = {}
                            for item in entity_chars:
                                if not isinstance(item, dict):
                                    continue
                                name = str(item.get("name") or "").strip()
                                raw_id = item.get("character_id") or item.get("entity_id") or item.get("id")
                                if name and raw_id is not None:
                                    id_by_name[name.lower()] = str(raw_id).strip()

                            if id_by_name:
                                updated = False
                                for profile in profiles:
                                    if not isinstance(profile, dict):
                                        continue
                                    name = str(profile.get("name") or "").strip()
                                    if not name:
                                        continue
                                    mapped_id = id_by_name.get(name.lower())
                                    if mapped_id and str(profile.get("character_id") or "").strip() != mapped_id:
                                        profile["character_id"] = mapped_id
                                        updated = True
                                if updated:
                                    ctx.payload["character_profiles"] = profiles

                        try:
                            from app.services.dreamweaver.library import enrich_payload_with_library

                            enrich_payload_with_library(
                                session,
                                ctx.payload,
                                project_id=project_id,
                                user_id=user_id,
                                max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
                                max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
                                max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
                            )
                        except Exception as e:
                            logger.debug("enrich_payload_with_library failed for project %s: %s", project_id, e)
            except Exception as e:
                logger.debug("Failed to enrich payload with library data for project %s: %s", project_id, e)

            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
                schema_version=schema_version_effective,
            )
            persist_contract(
                session,
                contract=contract,
                status="running",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
            )
            try:
                record_dreamweaver_billing_freeze(db=session, run_id=run_id)
            except Exception as exc:
                logger.warning("record_dreamweaver_billing_freeze failed trace_id=%s run_id=%s: %s", trace_ctx.get("trace_id"), run_id, exc)

            running_payload = {
                "run_id": run_id,
                "state": ctx.state.name,
                "stage": stage_label(ctx.state),
                "progress": progress_percent(ctx.state),
                "source_chapter_count": len(chapter_ids),
                "artifacts": {**_artifact_summary(ctx.payload), "stage_artifacts": _stage_artifacts(ctx.state, ctx.payload)},
            }
            _update_generation_history(
                task_id,
                status="running",
                result=json.dumps(running_payload, ensure_ascii=False),
                error=None,
            )

        if loop_exhausted and ctx.state not in (
            State.DONE,
            State.FAILED,
            State.WAITING_SCRIPT_APPROVAL,
            State.WAITING_APPROVAL,
            State.WAITING_VIDEO_CONFIRMATION,
        ):
            ctx.payload.setdefault(
                "error",
                f"pipeline step budget exhausted (max_steps={max_steps}, state={ctx.state.name})",
            )
            ctx.payload.setdefault("failed_from_state", ctx.state.name)
            ctx.state = State.FAILED

        if emitter is not None:
            emitter.emit_stage_end(
                stage=stage_label(ctx.state),
                state=ctx.state.name,
                progress=progress_percent(ctx.state),
            )

        result_payload = {
            "run_id": run_id,
            "state": ctx.state.name,
            "stage": stage_label(ctx.state),
            "progress": progress_percent(ctx.state),
            "source_chapter_count": len(chapter_ids),
            "artifacts": {**_artifact_summary(ctx.payload), "stage_artifacts": _stage_artifacts(ctx.state, ctx.payload)},
            "plan": ctx.payload.get("plan"),
            "storyboard": ctx.payload.get("storyboard"),
            "camera_tree_generation": ctx.payload.get("camera_tree_generation"),
            "camera_tree": ctx.payload.get("camera_tree"),
            "camera_states": ctx.payload.get("camera_states"),
            "camera_scenes": ctx.payload.get("camera_scenes"),
            "keyframes": ctx.payload.get("keyframes"),
            "midframes": ctx.payload.get("midframes"),
            "video_clips": ctx.payload.get("video_clips"),
            "merged_video": ctx.payload.get("merged_video"),
            "audit": ctx.payload.get("audit"),
            "autoqc": ctx.payload.get("autoqc"),
            "qc_warning": ctx.payload.get("qc_warning"),
            "preflight": ctx.payload.get("preflight"),
            "video_provider_trace": ctx.payload.get("video_provider_trace"),
        }

        if ctx.state == State.DONE:
            logger.info(
                "DreamWeaver run completed: trace_id=%s project_id=%s run_id=%s",
                trace_ctx.get("trace_id"),
                project_id,
                run_id,
            )
            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
            )
            persist_contract(
                session,
                contract=contract,
                status="completed",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
            )
            try:
                record_dreamweaver_billing_settle(db=session, run_id=run_id)
            except Exception as exc:
                logger.warning("record_dreamweaver_billing_settle failed trace_id=%s run_id=%s: %s", trace_ctx.get("trace_id"), run_id, exc)
            _update_generation_history(
                task_id,
                status="completed",
                result=json.dumps(result_payload, ensure_ascii=False),
                error=None,
                completed_at=utc_now().isoformat(),
            )
        elif ctx.state in (State.WAITING_SCRIPT_APPROVAL, State.WAITING_APPROVAL, State.WAITING_VIDEO_CONFIRMATION):
            logger.info(
                "DreamWeaver run waiting: trace_id=%s project_id=%s run_id=%s state=%s",
                trace_ctx.get("trace_id"),
                project_id,
                run_id,
                ctx.state.name,
            )
            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
            )
            persist_contract(
                session,
                contract=contract,
                status="waiting",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
            )
            _update_generation_history(
                task_id,
                status="waiting",
                result=json.dumps(result_payload, ensure_ascii=False),
                error=None,
                completed_at=utc_now().isoformat(),
            )
        else:
            error_message = str(ctx.payload.get("error") or "pipeline failed")
            failed_from_state = (
                str(ctx.payload.get("failed_from_state")).strip()
                if isinstance(ctx.payload.get("failed_from_state"), str)
                else None
            )
            failed_payload = {
                **result_payload,
                "error_type": "state_machine_failed",
                "error_message": error_message,
                "failed_state": failed_from_state or ctx.state.name,
                "failed_from_state": failed_from_state,
            }
            logger.warning(
                "DreamWeaver run failed: trace_id=%s project_id=%s run_id=%s failed_from_state=%s error=%s",
                trace_ctx.get("trace_id"),
                project_id,
                run_id,
                failed_from_state or ctx.state.name,
                error_message[:200],
            )
            contract = build_contract_from_payload(
                run_id=run_id,
                source_project_id=project_id,
                user_id=user_id,
                payload=ctx.payload,
            )
            persist_contract(
                session,
                contract=contract,
                status="failed",
                state=ctx.state.name,
                stage=stage_label(ctx.state),
                progress=progress_percent(ctx.state),
                error_type="state_machine_failed",
                error_message=error_message,
            )
            try:
                record_dreamweaver_billing_release(
                    db=session,
                    run_id=run_id,
                    reason="短剧任务失败，已释放冻结积分。",
                )
            except Exception as exc:
                logger.warning("record_dreamweaver_billing_release failed trace_id=%s run_id=%s: %s", trace_ctx.get("trace_id"), run_id, exc)
            _update_generation_history(
                task_id,
                status="failed",
                result=json.dumps(failed_payload, ensure_ascii=False),
                error=error_message,
                completed_at=utc_now().isoformat(),
            )
    except Exception as exc:  # pragma: no cover - safety
        logger.exception(
            "DreamWeaver task crashed: trace_id=%s project_id=%s run_id=%s error=%s",
            task_id,
            project_id,
            run_id,
            exc,
        )
        if emitter is not None:
            emitter.emit_event(
                stage=None,
                event_type="run_error",
                payload={"error": str(exc)},
            )
        try:
            session.rollback()
        except Exception as rollback_exc:
            logger.debug("session.rollback failed in exception handler for run_id=%s: %s", run_id, rollback_exc)
        try:
            record_dreamweaver_billing_release(
                db=session,
                run_id=run_id,
                reason="短剧任务异常中断，已释放冻结积分。",
            )
        except Exception as release_exc:
            logger.warning("record_dreamweaver_billing_release failed trace_id=%s run_id=%s: %s", task_id, run_id, release_exc)
        _update_generation_history(
            task_id,
            status="failed",
            error=str(exc),
            completed_at=utc_now().isoformat(),
        )
        raise
    finally:
        session.close()
