from __future__ import annotations

from app.api.v1.dreamweaver_api._imports import *

logger = logging.getLogger(__name__)

@router.get("/task/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询生成任务状态，优先融合 generation_history 与 DreamweaverProject 的状态信息。
    """
    query = text(
        """
        SELECT gh.task_id, gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
        FROM generation_history gh
        INNER JOIN projects p ON gh.project_id = p.id
        WHERE gh.task_id = :task_id AND p.user_id = :user_id
        """
    )
    row = db.execute(query, {"task_id": task_id, "user_id": current_user.id}).fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或无权限访问"
        )

    status_str = row[1]
    progress = 50 if status_str == "running" else 100 if status_str == "completed" else 0
    progress_from_payload = False

    run_id: Optional[str] = None
    queue: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    artifacts: Optional[dict] = None
    error_type: Optional[str] = None
    parsed_result: Optional[RunResponse] = None
    if row[2]:
        try:
            payload = json.loads(row[2])
            if isinstance(payload, dict):
                run_id = payload.get("run_id")
                queue = payload.get("queue") if isinstance(payload.get("queue"), str) else None
                state = payload.get("state")
                stage = payload.get("stage")
                artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else None
                error_type = payload.get("error_type") if isinstance(payload.get("error_type"), str) else None
                if isinstance(payload.get("progress"), int):
                    progress = payload["progress"]
                    progress_from_payload = True
                if status_str == "completed" and {"run_id", "state", "source_chapter_count"}.issubset(payload):
                    parsed_result = RunResponse(**payload)
        except Exception as e:
            logger.debug("Failed to parse run result from generation_history: %s", e)
            run_id = None

    # generation_history 保存的是兼容 SQLite 的通用任务状态。
    # DreamweaverProject.contract_json 保存更完整的运行上下文，用于补充 UI 需要的信息。
    dw_row = None
    if isinstance(run_id, str) and run_id.strip():
        dw_row = (
            db.query(DreamweaverProjectModel)
            .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
            .first()
        )
        if dw_row is not None:
            dw_status = str(getattr(dw_row, "status", "") or "").strip().lower()

            # generation_history.status 在 SQLite 模型下可能落后于实际运行状态。
            # DreamweaverProject.status 用于修正 queued/running 等过渡阶段，让 UI 显示更准确。
            if status_str == "queued":
                if dw_status in {"running", "completed", "failed"}:
                    status_str = dw_status
                elif dw_status == "waiting" and not progress_from_payload:
                    status_str = dw_status
            elif status_str == "running" and dw_status in {"waiting", "completed", "failed"}:
                status_str = dw_status

            dw_progress = getattr(dw_row, "progress", None)
            if isinstance(dw_progress, int):
                # 实际进度优先使用 DreamweaverProject.progress 修正后的值。
                # generation_history.result 里的 progress/state/stage 更像是任务快照。
                # - generation_history.progress 适合用于补充过程中状态。
                # - DreamweaverProject.progress 适合作为最终进度显示。
                should_override = (not progress_from_payload) or (dw_progress > progress)
                if should_override:
                    progress = int(dw_progress)
                    if isinstance(getattr(dw_row, "state", None), str) and str(dw_row.state).strip():
                        state = str(dw_row.state)
                    if isinstance(getattr(dw_row, "stage", None), str) and str(dw_row.stage).strip():
                        stage = str(dw_row.stage)
            else:
                if not state and isinstance(getattr(dw_row, "state", None), str) and str(dw_row.state).strip():
                    state = str(dw_row.state)
                if not stage and isinstance(getattr(dw_row, "stage", None), str) and str(dw_row.stage).strip():
                    stage = str(dw_row.stage)
            if not error_type and isinstance(getattr(dw_row, "error_type", None), str) and str(dw_row.error_type).strip():
                error_type = str(dw_row.error_type)

    error_message = row[3]
    if (not isinstance(error_message, str) or not error_message.strip()) and status_str == "failed":
        if isinstance(run_id, str) and run_id.strip():
            if dw_row is not None and isinstance(getattr(dw_row, "error_message", None), str) and str(dw_row.error_message).strip():
                error_message = str(dw_row.error_message)

    return TaskStatusResponse(
        task_id=row[0],
        status=status_str,
        progress=progress,
        run_id=run_id,
        queue=queue,
        state=state,
        stage=stage,
        artifacts=artifacts,
        error_type=error_type,
        result=parsed_result,
        error=error_message,
    )

