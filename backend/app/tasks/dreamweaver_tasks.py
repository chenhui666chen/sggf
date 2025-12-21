"""
Celery tasks for DreamWeaver mock pipeline.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from app.celery_app import celery_app
from app.db.base import SessionLocal
from app.models.project import Project
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION
from pipeline.state_machine import RunContext, State, progress_percent, stage_label, step

logger = logging.getLogger(__name__)


def _stage_artifacts(state: State, payload: Dict[str, Any]) -> Dict[str, Any]:
    storyboard = payload.get("storyboard") or []
    keyframes = payload.get("keyframes") or []
    midframes = payload.get("midframes") or []
    video_clips = payload.get("video_clips") or []

    last_storyboard_shot_id = None
    if isinstance(storyboard, list) and storyboard:
        last_item = storyboard[-1]
        if isinstance(last_item, dict):
            last_storyboard_shot_id = last_item.get("shot_id")

    audit = payload.get("audit")
    audit_pass = None
    issues_count = None
    if isinstance(audit, dict):
        audit_pass = audit.get("pass")
        issues = audit.get("issues")
        issues_count = len(issues) if isinstance(issues, list) else None

    autoqc = payload.get("autoqc")
    autoqc_pass = None
    autoqc_score = None
    if isinstance(autoqc, dict):
        autoqc_pass = autoqc.get("pass")
        if isinstance(autoqc.get("overall_score"), (int, float)):
            autoqc_score = float(autoqc["overall_score"])

    stage_specific: Dict[str, Any] = {
        "state": state.name,
        "stage": stage_label(state),
    }

    if state == State.SCRIPT:
        stage_specific["plan_text"] = (payload.get("plan") or {}).get("text") if isinstance(payload.get("plan"), dict) else None
    elif state == State.STORYBOARD:
        stage_specific["storyboard_count"] = len(storyboard) if isinstance(storyboard, list) else 0
        stage_specific["last_storyboard_shot_id"] = last_storyboard_shot_id
    elif state == State.KEYFRAMES:
        stage_specific["keyframes_paths"] = [i.get("path") for i in keyframes[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.MIDFRAMES:
        stage_specific["midframes_paths"] = [i.get("path") for i in midframes[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.VIDEO:
        stage_specific["video_clips_paths"] = [i.get("path") for i in video_clips[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.EDIT:
        stage_specific["merged_video"] = payload.get("merged_video")
    elif state == State.REVIEW:
        stage_specific["audit_pass"] = audit_pass
        stage_specific["issues_count"] = issues_count
        stage_specific["autoqc_pass"] = autoqc_pass
        stage_specific["autoqc_overall_score"] = autoqc_score
    elif state == State.REWORK:
        stage_specific["rework_reason"] = payload.get("rework_reason")

    return stage_specific


def _artifact_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    storyboard = payload.get("storyboard") or []
    keyframes = payload.get("keyframes") or []
    midframes = payload.get("midframes") or []
    video_clips = payload.get("video_clips") or []

    audit = payload.get("audit")
    audit_pass = None
    if isinstance(audit, dict):
        audit_pass = audit.get("pass")

    autoqc = payload.get("autoqc")
    autoqc_pass = None
    autoqc_score = None
    autoqc_route = None
    if isinstance(autoqc, dict):
        autoqc_pass = autoqc.get("pass")
        autoqc_route = autoqc.get("route")
        if isinstance(autoqc.get("overall_score"), (int, float)):
            autoqc_score = float(autoqc["overall_score"])

    def safe_len(value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    def last_path(items: Any) -> Any:
        if not isinstance(items, list) or not items:
            return None
        last = items[-1]
        if isinstance(last, dict):
            return last.get("path")
        return None

    def tail_paths(items: Any, limit: int = 3) -> List[str]:
        if not isinstance(items, list) or not items:
            return []
        paths: List[str] = []
        for item in items[-limit:]:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
        return paths

    return {
        "has_plan": bool(payload.get("plan")),
        "storyboard_count": safe_len(storyboard),
        "keyframes_count": safe_len(keyframes),
        "last_keyframe_path": last_path(keyframes),
        "keyframes_tail_paths": tail_paths(keyframes),
        "midframes_count": safe_len(midframes),
        "last_midframe_path": last_path(midframes),
        "midframes_tail_paths": tail_paths(midframes),
        "video_clips_count": safe_len(video_clips),
        "last_video_clip_path": last_path(video_clips),
        "video_clips_tail_paths": tail_paths(video_clips),
        "merged_video": payload.get("merged_video"),
        "audit_pass": audit_pass,
        "autoqc_pass": autoqc_pass,
        "autoqc_overall_score": autoqc_score,
        "autoqc_route": autoqc_route,
        "rework_reason": payload.get("rework_reason"),
    }


def _update_generation_history(task_id: str, **changes: Any) -> None:
    session = SessionLocal()
    try:
        set_parts = []
        params: Dict[str, Any] = {"task_id": task_id}
        for key, value in changes.items():
            set_parts.append(f"{key} = :{key}")
            params[key] = value
        if not set_parts:
            return
        query = text(
            f"""
            UPDATE generation_history
            SET {", ".join(set_parts)}
            WHERE task_id = :task_id
            """
        )
        session.execute(query, params)
        session.commit()
    finally:
        session.close()


@celery_app.task(name="dreamweaver.mock_run", bind=True)
def run_dreamweaver_mock_task(
    self,
    task_id: str,
    run_id: str,
    project_id: int,
    *args: Any,
) -> None:
    """
    Run DreamWeaver mock pipeline asynchronously and persist the result into generation_history.
    """
    from app.services.dreamweaver.persistence import build_contract_from_payload, persist_contract

    session = SessionLocal()
    try:
        # 兼容旧队列消息：历史版本参数为 (task_id, run_id, project_id, chapter_ids, source_text)
        # 新版本参数为 (task_id, run_id, project_id, user_id, chapter_ids, source_text)
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

        ctx = RunContext(
            run_id=run_id,
            payload={
                "project_id": project_id,
                "chapter_ids": chapter_ids,
                "source_text": source_text,
                "schema_version": schema_version_effective,
            },
        )
        # 逐步执行，实时写入 progress/state，便于前端轮询展示
        max_steps = 50
        for _ in range(max_steps):
            if ctx.state in (State.DONE, State.FAILED):
                break
            ctx = step(ctx)
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

        result_payload = {
            "run_id": run_id,
            "state": ctx.state.name,
            "stage": stage_label(ctx.state),
            "progress": progress_percent(ctx.state),
            "source_chapter_count": len(chapter_ids),
            "artifacts": {**_artifact_summary(ctx.payload), "stage_artifacts": _stage_artifacts(ctx.state, ctx.payload)},
            "plan": ctx.payload.get("plan"),
            "storyboard": ctx.payload.get("storyboard"),
            "keyframes": ctx.payload.get("keyframes"),
            "midframes": ctx.payload.get("midframes"),
            "video_clips": ctx.payload.get("video_clips"),
            "merged_video": ctx.payload.get("merged_video"),
            "audit": ctx.payload.get("audit"),
        }

        if ctx.state == State.DONE:
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
            _update_generation_history(
                task_id,
                status="completed",
                result=json.dumps(result_payload, ensure_ascii=False),
                error=None,
                completed_at=datetime.now().isoformat(),
            )
        else:
            error_message = str(ctx.payload.get("error") or "pipeline failed")
            failed_payload = {
                **result_payload,
                "error_type": "state_machine_failed",
                "error_message": error_message,
                "failed_state": ctx.state.name,
            }
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
            _update_generation_history(
                task_id,
                status="failed",
                result=json.dumps(failed_payload, ensure_ascii=False),
                error=error_message,
                completed_at=datetime.now().isoformat(),
            )
    except Exception as exc:  # pragma: no cover - safety
        logger.exception("DreamWeaver mock task failed: %s", exc)
        _update_generation_history(
            task_id,
            status="failed",
            error=str(exc),
            completed_at=datetime.now().isoformat(),
        )
        raise
    finally:
        session.close()
