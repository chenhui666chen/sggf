from __future__ import annotations

from app.api.v1.dreamweaver_api._imports import *
from app.api.v1.dreamweaver_api._helpers import (
    _dreamweaver_celery_queue,
    _ensure_run_not_running,
    _find_latest_generation_history_for_run,
    _load_run_for_user,
    _normalize_run_id,
    _parse_generation_history_result_payload,
)

logger = logging.getLogger(__name__)

@router.get("/runs/{run_id}/script", response_model=dict)
def get_run_script(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        # 优先回退到 generation_history 查找旧运行记录。
        gh_query = text(
            """
            SELECT gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
            FROM generation_history gh
            INNER JOIN projects p ON gh.project_id = p.id
            WHERE p.user_id = :user_id
              AND gh.task_type = 'dreamweaver'
              AND gh.result LIKE :needle
            ORDER BY gh.created_at DESC
            LIMIT 1
            """
        )
        needle = f'%\"run_id\": \"{run_id}\"%'
        gh_row = db.execute(gh_query, {"user_id": current_user.id, "needle": needle}).fetchone()
        if not gh_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权限访问")

        status_str = str(gh_row[0] or "").strip()
        result_raw = gh_row[1]
        error_message = gh_row[2] if isinstance(gh_row[2], str) and gh_row[2].strip() else None
        state = None
        stage = None
        progress = None
        error_type = None
        if isinstance(result_raw, str) and result_raw.strip():
            try:
                payload = json.loads(result_raw)
                if isinstance(payload, dict) and str(payload.get("run_id") or "").strip() == run_id:
                    if isinstance(payload.get("state"), str):
                        state = str(payload.get("state") or "").strip() or None
                    if isinstance(payload.get("stage"), str):
                        stage = str(payload.get("stage") or "").strip() or None
                    if isinstance(payload.get("progress"), int):
                        progress = int(payload.get("progress"))
                    if isinstance(payload.get("error_type"), str):
                        error_type = str(payload.get("error_type") or "").strip() or None
                    if not error_message and isinstance(payload.get("error_message"), str):
                        error_message = str(payload.get("error_message") or "").strip() or None
            except Exception as e:
                logger.debug("Failed to extract error info from payload: %s", e)

        if not isinstance(progress, int):
            if status_str == "running":
                progress = 50
            elif status_str == "completed":
                progress = 100
            else:
                progress = 0

        return {
            "dreamweaver_project_id": None,
            "run_id": run_id,
            "status": status_str or "queued",
            "state": state,
            "stage": stage,
            "progress": progress,
            "schema_version": "",
            "error_type": error_type,
            "error_message": error_message,
            "contract": None,
        }

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    script_text = runtime_cfg.get("script_text") if isinstance(runtime_cfg.get("script_text"), str) else ""
    script_entities = runtime_cfg.get("script_entities") if isinstance(runtime_cfg.get("script_entities"), dict) else {}
    script_generation = runtime_cfg.get("script_generation") if isinstance(runtime_cfg.get("script_generation"), dict) else {}
    script_review = runtime_cfg.get("script_review") if isinstance(runtime_cfg.get("script_review"), dict) else {"approved": False}
    script_requires_review = bool(runtime_cfg.get("script_requires_review"))
    style_preset = runtime_cfg.get("style_preset") if isinstance(runtime_cfg.get("style_preset"), str) else None

    return {
        "run_id": row.run_id,
        "project_id": int(row.source_project_id),
        "status": row.status,
        "state": row.state,
        "stage": row.stage,
        "progress": row.progress,
        "style_preset": style_preset,
        "script_text": script_text,
        "script_entities": script_entities,
        "script_generation": script_generation,
        "script_review": script_review,
        "script_requires_review": script_requires_review,
        "script_document": runtime_cfg.get("script_document")
        if isinstance(runtime_cfg.get("script_document"), dict)
        else {},
        "story_graph": runtime_cfg.get("story_graph")
        if isinstance(runtime_cfg.get("story_graph"), dict)
        else {},
    }


@router.post("/runs/{run_id}/script", response_model=dict)
def update_run_script(
    run_id: str,
    request: ScriptUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _load_run_for_user(db, run_id, current_user.id)

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不在脚本审核阶段")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    runtime_cfg["script_text"] = request.script_text.strip() + "\n"
    runtime_cfg["script_review"] = {"approved": False}
    runtime_cfg["script_requires_review"] = True
    runtime_cfg["script_generation"] = {"mode": "manual", "model": None, "error": None}
    contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": row.run_id, "updated": True, "script_review": runtime_cfg["script_review"]}


@router.post("/runs/{run_id}/script/approve", response_model=dict)
def approve_run_script(
    run_id: str,
    request: ScriptApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _load_run_for_user(db, run_id, current_user.id)

    if str(row.stage or "").strip() != "waiting_script_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不在脚本审核阶段")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    approved = bool(request.approved)
    runtime_cfg["script_review"] = {"approved": approved}
    runtime_cfg["script_requires_review"] = not approved
    contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": row.run_id, "approved": approved}


@router.post("/runs/{run_id}/prompt-review/approve", response_model=dict)
def approve_prompt_review(
    run_id: str,
    request: PromptReviewApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _load_run_for_user(db, run_id, current_user.id)

    stage = str(row.stage or "").strip().lower()
    if stage != "waiting_approval":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不在提示词审核阶段")

    _ensure_run_not_running(row, action="提交提示词审核")

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    approved = bool(request.approved)
    if "prompt_review_required" not in runtime_cfg:
        runtime_cfg["prompt_review_required"] = True
    runtime_cfg["prompt_review"] = {"approved": approved}
    contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    flag_modified(row, "contract_json")
    db.commit()

    return {"run_id": row.run_id, "approved": approved}


@router.post("/runs/{run_id}/safety-audit/approve", response_model=SafetyAuditApproveResponse)
def approve_safety_audit_failure(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    safe_run_id = _normalize_run_id(run_id)
    row = _load_run_for_user(db, safe_run_id, current_user.id)
    _ensure_run_not_running(row, action="安全审核人工放行")

    if str(row.status or "").strip().lower() != "failed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只有失败的 run 才能执行人工放行")

    contract = copy.deepcopy(row.contract_json) if isinstance(row.contract_json, dict) else {}
    runtime_cfg = copy.deepcopy(contract.get("runtime_config")) if isinstance(contract.get("runtime_config"), dict) else {}

    history_row = _find_latest_generation_history_for_run(db, user_id=int(current_user.id), run_id=safe_run_id)
    history_payload = _parse_generation_history_result_payload(history_row)
    safety_context = _extract_safety_audit_override_context(
        row=row,
        contract=contract,
        history_payload=history_payload,
    )
    if safety_context is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不是可以人工放行的安全审核阻断任务")

    audit = safety_context["audit"]
    rework_reason = safety_context["rework_reason"]
    safety_audit = safety_context["safety_audit"]

    override_at = utc_now().isoformat()
    override_by = str(getattr(current_user, "username", None) or f"user:{current_user.id}")

    original_error_type = str(runtime_cfg.get("error_type") or row.error_type or "").strip()
    original_error_message = str(runtime_cfg.get("error_message") or row.error_message or "").strip()
    if not original_error_type and isinstance(history_payload, dict) and isinstance(history_payload.get("error_type"), str):
        original_error_type = str(history_payload.get("error_type") or "").strip()
    if not original_error_message:
        if isinstance(history_payload, dict) and isinstance(history_payload.get("error_message"), str):
            original_error_message = str(history_payload.get("error_message") or "").strip()
        elif hasattr(history_row, "get") and isinstance(history_row.get("error"), str):
            original_error_message = str(history_row.get("error") or "").strip()

    if original_error_type and not str(safety_audit.get("original_error_type") or "").strip():
        safety_audit["original_error_type"] = original_error_type
    if original_error_message and not str(safety_audit.get("original_error_message") or "").strip():
        safety_audit["original_error_message"] = original_error_message
    if original_error_message and not str(safety_audit.get("summary") or "").strip():
        safety_audit["summary"] = original_error_message

    safety_audit["manual_override"] = True
    safety_audit["manual_override_at"] = override_at
    safety_audit["manual_override_by"] = override_by
    safety_audit["manual_override_user_id"] = int(current_user.id)
    safety_audit["effective_pass"] = True
    safety_audit["effective_blocked"] = False

    audit["safety_audit"] = safety_audit

    rework_reason["type"] = "safety_audit_failed"
    rework_reason["manual_override"] = True
    rework_reason["manual_override_at"] = override_at
    rework_reason["manual_override_by"] = override_by
    rework_reason["manual_override_user_id"] = int(current_user.id)
    rework_reason["safety_audit"] = safety_audit

    runtime_cfg["audit"] = audit
    runtime_cfg["rework_reason"] = rework_reason
    runtime_cfg.pop("error_type", None)
    runtime_cfg.pop("error_message", None)
    runtime_cfg.pop("failed_from_state", None)
    contract["runtime_config"] = runtime_cfg

    row.contract_json = contract
    row.status = "completed"
    row.state = "DONE"
    row.stage = "done"
    row.progress = 100
    row.error_type = None
    row.error_message = None
    flag_modified(row, "contract_json")

    if history_row and history_row.get("id") is not None:
        updated_payload = copy.deepcopy(history_payload) if isinstance(history_payload, dict) else {"run_id": safe_run_id}
        updated_payload["state"] = "DONE"
        updated_payload["stage"] = "done"
        updated_payload["progress"] = 100
        updated_payload["audit"] = audit
        artifacts = updated_payload.get("artifacts") if isinstance(updated_payload.get("artifacts"), dict) else {}
        artifacts["rework_reason"] = rework_reason
        updated_payload["artifacts"] = artifacts
        updated_payload.pop("error_type", None)
        updated_payload.pop("error_message", None)
        updated_payload.pop("failed_state", None)
        updated_payload.pop("failed_from_state", None)

        db.execute(
            text(
                """
                UPDATE generation_history
                SET status = :status,
                    result = :result,
                    error = :error,
                    completed_at = :completed_at
                WHERE id = :id
                """
            ),
            {
                "id": int(history_row["id"]),
                "status": "completed",
                "result": json.dumps(updated_payload, ensure_ascii=False),
                "error": None,
                "completed_at": override_at,
            },
        )

    db.commit()

    return SafetyAuditApproveResponse(
        run_id=row.run_id,
        status=row.status,
        state=row.state,
        stage=row.stage,
        manual_override=True,
    )


@router.post("/runs/{run_id}/resume-async", response_model=ResumeAsyncResponse)
def resume_run_async(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _load_run_for_user(db, run_id, current_user.id)

    project_id = int(row.source_project_id)

    state = str(row.state or "").strip()
    stage = str(row.stage or "").strip()
    # waiting_* 阶段优先使用 stage，缺失时再回退到 state。
    waiting_kind = stage or state
    start_state = "STORYBOARD"

    contract = row.contract_json if isinstance(row.contract_json, dict) else {}
    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}

    if waiting_kind == "waiting_script_approval" or waiting_kind == "WAITING_SCRIPT_APPROVAL":
        script_review = runtime_cfg.get("script_review") if isinstance(runtime_cfg.get("script_review"), dict) else {}
        approved = bool(script_review.get("approved"))
        requires_review = bool(runtime_cfg.get("script_requires_review"))
        if requires_review and not approved:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "脚本审核未通过，无法继续", "script_review": script_review})
        start_state = "STORYBOARD"
    elif waiting_kind == "waiting_approval" or waiting_kind == "WAITING_APPROVAL":
        spec = (
            _build_scoped_library_spec_from_run(
                db,
                project_id=project_id,
                user_id=current_user.id,
                run_id=run_id,
                strict=True,
            )
            or empty_library_spec(project_id=project_id)
        )
        spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=spec)
        assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=current_user.id)
        review = compute_library_review(spec=spec, assets_by_role=assets_by_role)
        if not bool(review.get("approved")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "素材库审核未通过，无法继续", "review": review})
        prompt_review_required = bool(runtime_cfg.get("prompt_review_required"))
        prompt_review = runtime_cfg.get("prompt_review") if isinstance(runtime_cfg.get("prompt_review"), dict) else {}
        prompt_review_approved = bool(prompt_review.get("approved"))
        if prompt_review_required and not prompt_review_approved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "提示词审核未通过，无法继续", "prompt_review": prompt_review},
            )
        start_state = "KEYFRAMES"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不在可恢复状态")

    task_id = str(uuid.uuid4())
    try:
        start_state_enum = State[start_state]
    except (KeyError, AttributeError):  # noqa: BLE001
        logger.warning("Invalid start_state '%s' for script restart, falling back to INIT", start_state)
        start_state_enum = State.INIT
    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, result, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :result, :created_at)
        """
    )
    # 恢复任务时需要先将 waiting_* 运行状态重新推进到 queued。
    # DreamweaverProject 与 generation_history 都会用同一个 task_id 继续执行后续流程。
    row.status = "queued"
    row.state = start_state
    row.stage = stage_label(start_state_enum)
    row.progress = progress_percent(start_state_enum)
    row.error_type = None
    row.error_message = None
    db.execute(
        insert_query,
        {
            "project_id": project_id,
            "task_type": "dreamweaver",
            "task_id": task_id,
            "status": "queued",
            "result": json.dumps(
                {
                    "run_id": run_id,
                    "state": start_state,
                    "stage": stage_label(start_state_enum),
                    "progress": progress_percent(start_state_enum),
                    "queue": _dreamweaver_celery_queue(),
                },
                ensure_ascii=False,
            ),
            "created_at": utc_now().isoformat(),
        },
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

    schema_version = row.schema_version or DREAMWEAVER_SCHEMA_VERSION
    resume_config = {"resume": True, "start_state": start_state}
    task_args: List[Any] = [task_id, run_id, project_id, current_user.id, [], "", schema_version, resume_config]
    run_dreamweaver_task.apply_async(args=task_args, queue=_dreamweaver_celery_queue(), task_id=task_id)

    return ResumeAsyncResponse(task_id=task_id, run_id=run_id, status="queued")


@router.post("/runs/{run_id}/video-jobs/{shot_id}/confirm-async", response_model=VideoJobConfirmAsyncResponse)
def confirm_video_job_async(
    run_id: str,
    shot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    safe_run_id = _normalize_run_id(run_id)
    safe_shot_id = str(shot_id or "").strip()
    if not safe_shot_id or "/" in safe_shot_id or "\\" in safe_shot_id or ".." in safe_shot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id 格式不合法")

    row = _load_run_for_user(db, safe_run_id, current_user.id)
    _ensure_run_not_running(row, action="确认视频任务")

    stage = str(getattr(row, "stage", "") or "").strip().lower()
    state = str(getattr(row, "state", "") or "").strip().upper()
    if stage != "waiting_video_confirmation" and state != "WAITING_VIDEO_CONFIRMATION":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不在视频确认阶段")

    contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else None
    if not isinstance(contract, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="contract_json 缺失或无效")

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
    jobs = runtime_cfg.get("video_clip_jobs")
    if not isinstance(jobs, list) or not jobs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前 run 不存在可确认的 video_clip_jobs")

    target_job = None
    for item in jobs:
        if not isinstance(item, dict):
            continue
        if str(item.get("shot_id") or "").strip() == safe_shot_id:
            target_job = item
            break
    if not isinstance(target_job, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到对应的 shot 视频任务")

    target_job["confirmed"] = True
    target_job["confirmed_ts"] = float(time.time())

    runtime_cfg["video_clip_jobs"] = jobs
    contract["runtime_config"] = runtime_cfg
    row.contract_json = contract
    flag_modified(row, "contract_json")

    def _has_video_clip_asset(contract_shot: dict) -> bool:
        assets = contract_shot.get("assets") if isinstance(contract_shot.get("assets"), list) else []
        for a in assets:
            if not isinstance(a, dict):
                continue
            if str(a.get("role") or "") != "video_clip":
                continue
            uri = a.get("uri")
            if isinstance(uri, str) and uri.strip():
                return True
        return False

    episodes = contract.get("episodes") if isinstance(contract.get("episodes"), list) else []
    generated_shots: set[str] = set()
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        shots = ep.get("shots") if isinstance(ep.get("shots"), list) else []
        for sh in shots:
            if not isinstance(sh, dict):
                continue
            shot_key = str(sh.get("shot_key") or "").strip()
            if not shot_key:
                continue
            if _has_video_clip_asset(sh):
                generated_shots.add(shot_key)

    run_dir = Path("runs") / safe_run_id
    for item in jobs:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("shot_id") or "").strip()
        if not sid or sid in generated_shots:
            continue
        outputs = item.get("outputs") if isinstance(item.get("outputs"), dict) else {}
        out_raw = outputs.get("clip") if isinstance(outputs.get("clip"), str) else None
        out_path: Optional[Path] = None
        if isinstance(out_raw, str) and out_raw.strip():
            out_path = Path(out_raw)
        elif run_dir.exists():
            out_path = run_dir / f"{sid}.mp4"
        if out_path is not None and out_path.exists():
            generated_shots.add(sid)

    ready: List[str] = []
    available: set[str] = set(generated_shots)
    for item in jobs:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("shot_id") or "").strip()
        if not sid:
            continue
        if sid in generated_shots:
            item["status"] = "done"
            available.add(sid)
            continue
        if not bool(item.get("confirmed")):
            item["status"] = "draft"
            continue
        requires_bridge = bool(item.get("requires_bridge"))
        dep = str(item.get("depends_on_shot_id") or "").strip()
        if requires_bridge and (not dep or dep not in available):
            item["status"] = "blocked"
            continue
        item["status"] = "confirmed"
        ready.append(sid)
        available.add(sid)

    if safe_shot_id in generated_shots:
        db.commit()
        return VideoJobConfirmAsyncResponse(
            run_id=safe_run_id,
            status="noop",
            message="该镜头的视频片段已生成，无需重复确认",
            video_clip_jobs=jobs,
        )

    if not ready:
        db.commit()
        return VideoJobConfirmAsyncResponse(
            run_id=safe_run_id,
            status="blocked",
            message="当前镜头仍有前置依赖未满足，暂时无法进入视频生成",
            video_clip_jobs=jobs,
        )

    project_id = int(getattr(row, "source_project_id", 0) or 0)
    if project_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run 缺少有效的 source_project_id")

    task_id = str(uuid.uuid4())
    start_state_enum = State.VIDEO

    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, result, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :result, :created_at)
        """
    )

    row.status = "queued"
    row.state = "VIDEO"
    row.stage = stage_label(start_state_enum)
    row.progress = progress_percent(start_state_enum)
    row.error_type = None
    row.error_message = None
    db.execute(
        insert_query,
        {
            "project_id": project_id,
            "task_type": "dreamweaver",
            "task_id": task_id,
            "status": "queued",
            "result": json.dumps(
                {
                    "run_id": safe_run_id,
                    "state": "VIDEO",
                    "stage": stage_label(start_state_enum),
                    "progress": progress_percent(start_state_enum),
                    "queue": _dreamweaver_celery_queue(),
                },
                ensure_ascii=False,
            ),
            "created_at": utc_now().isoformat(),
        },
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

    schema_version = row.schema_version or DREAMWEAVER_SCHEMA_VERSION
    resume_config = {"resume": True, "start_state": "VIDEO", "reset_policy": "none"}
    task_args: List[Any] = [task_id, safe_run_id, project_id, current_user.id, [], "", schema_version, resume_config]
    run_dreamweaver_task.apply_async(args=task_args, queue=_dreamweaver_celery_queue(), task_id=task_id)

    return VideoJobConfirmAsyncResponse(
        run_id=safe_run_id,
        status="queued",
        task_id=task_id,
        message="已加入视频生成队列",
        video_clip_jobs=jobs,
    )

