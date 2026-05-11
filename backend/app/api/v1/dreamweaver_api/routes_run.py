from __future__ import annotations

from app.api.v1.dreamweaver_api._imports import *
from app.api.v1.dreamweaver_api._helpers import _dreamweaver_celery_queue, _load_project_chapters

logger = logging.getLogger(__name__)

@router.post("/run", response_model=RunResponse)
def run_pipeline(
    request: RunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建 DreamWeaver 运行并返回同步执行结果。
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限访问"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="章节不存在或为空"
        )

    source_text = _build_source_text(chapters)
    chapter_id_list = [c.id for c in chapters]
    schema_version = request.schema_version or DREAMWEAVER_SCHEMA_VERSION

    locked_cfg = get_project_locked_generation_config(db, project_id=request.project_id, user_id=current_user.id)
    try:
        enforce_locked_generation_config_compatible(
            locked_cfg,
            style_preset=request.style_preset,
            image_ratio=request.image_ratio,
            image_resolution=request.image_resolution,
            image_model=request.image_model,
            video_model=request.video_model,
            vision_model=request.vision_model,
            video_edit_model=request.video_edit_model,
            enable_video_edit=request.enable_video_edit,
            enable_vision_review=request.enable_vision_review,
            enable_safety_audit=request.enable_safety_audit,
            safety_fail_policy=request.safety_fail_policy,
        )
    except DreamweaverProjectConfigLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_locked_generation_config_error_detail(
                "当前项目的生成配置已锁定，新建 DreamWeaver 运行必须与锁定配置保持一致。",
                exc,
            ),
        ) from exc

    runtime_config = apply_locked_generation_config(
        _build_dreamweaver_runtime_config_from_request(request),
        locked_cfg,
    )
    request_preflight = build_dreamweaver_run_preflight(
        quality_mode=request.quality_mode,
        smart_tuning=request.smart_tuning,
        qc_allow_fail=request.qc_allow_fail,
        video_require_confirmation=request.video_require_confirmation,
        runtime_config=runtime_config,
    )
    _ensure_dreamweaver_request_preflight_passed(request_preflight)
    video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
    video_cfg.update(copy.deepcopy(request_preflight.resolved_video_config))
    runtime_config["video_config"] = video_cfg
    runtime_config["preflight"] = request_preflight.to_dict()
    precheck = build_dreamweaver_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=request.project_id,
        project_title=project.title,
        chapter_rows=chapters,
        chapter_ids=chapter_id_list,
        runtime_config=runtime_config,
        schema_version=schema_version,
    )
    _ensure_dreamweaver_points_precheck_passed(precheck)

    run_id = f"drama_{request.project_id}_{int(time.time())}"

    payload: Dict[str, Any] = {
        "project_id": request.project_id,
        "chapter_ids": chapter_id_list,
        "source_text": source_text,
    }
    payload.update(copy.deepcopy(runtime_config))

    enrich_payload_with_library(
        db,
        payload,
        project_id=request.project_id,
        user_id=current_user.id,
        max_characters=_env_int("DREAMWEAVER_LIBRARY_MAX_CHARACTERS", 12),
        max_scenes=_env_int("DREAMWEAVER_LIBRARY_MAX_SCENES", 8),
        max_props=_env_int("DREAMWEAVER_LIBRARY_MAX_PROPS", 8),
    )

    ctx = RunContext(run_id=run_id, payload=payload)

    ctx = run_until_done(ctx)

    # 将已完成的合同快照持久化到 DreamWeaver 项目记录。
    try:
        from app.services.dreamweaver.persistence import build_contract_from_payload, persist_contract

        contract = build_contract_from_payload(
            run_id=run_id,
            source_project_id=request.project_id,
            user_id=current_user.id,
            payload=ctx.payload,
            schema_version=schema_version,
        )
        persist_contract(
            db,
            contract=contract,
            status="completed"
            if ctx.state.name == "DONE"
            else "waiting"
            if ctx.state.name in {"WAITING_SCRIPT_APPROVAL", "WAITING_APPROVAL", "WAITING_VIDEO_CONFIRMATION"}
            else "failed",
            state=ctx.state.name,
            stage=stage_label(ctx.state),
            progress=progress_percent(ctx.state),
        )
    except Exception as e:
        logger.debug("Failed to persist contract for run_id=%s: %s", run_id, e)

    return RunResponse(
        run_id=run_id,
        state=ctx.state.name,
        stage=stage_label(ctx.state),
        progress=progress_percent(ctx.state),
        source_chapter_count=len(chapters),
        plan=ctx.payload.get("plan"),
        storyboard=ctx.payload.get("storyboard"),
        camera_tree_generation=ctx.payload.get("camera_tree_generation"),
        camera_tree=ctx.payload.get("camera_tree"),
        camera_states=ctx.payload.get("camera_states"),
        camera_scenes=ctx.payload.get("camera_scenes"),
        keyframes=ctx.payload.get("keyframes"),
        midframes=ctx.payload.get("midframes"),
        video_clips=ctx.payload.get("video_clips"),
        merged_video=ctx.payload.get("merged_video"),
        audit=ctx.payload.get("audit"),
        autoqc=ctx.payload.get("autoqc"),
        qc_warning=ctx.payload.get("qc_warning"),
        preflight=ctx.payload.get("preflight"),
        video_provider_trace=ctx.payload.get("video_provider_trace"),
        smart_dispatch_trace=ctx.payload.get("smart_dispatch_trace"),
    )


@router.post("/run-async", response_model=RunAsyncResponse)
def run_pipeline_async(
    request: RunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    以异步方式创建 DreamWeaver 运行。
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权限访问"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="章节不存在或为空"
        )

    locked_cfg = get_project_locked_generation_config(db, project_id=request.project_id, user_id=current_user.id)
    try:
        enforce_locked_generation_config_compatible(
            locked_cfg,
            style_preset=request.style_preset,
            image_ratio=request.image_ratio,
            image_resolution=request.image_resolution,
            image_model=request.image_model,
            video_model=request.video_model,
            vision_model=request.vision_model,
            video_edit_model=request.video_edit_model,
            enable_video_edit=request.enable_video_edit,
            enable_vision_review=request.enable_vision_review,
            enable_safety_audit=request.enable_safety_audit,
            safety_fail_policy=request.safety_fail_policy,
        )
    except DreamweaverProjectConfigLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_locked_generation_config_error_detail(
                "当前项目的生成配置已锁定，新建 DreamWeaver 运行必须与锁定配置保持一致。",
                exc,
            ),
        ) from exc

    source_text = _build_source_text(chapters)
    chapter_id_list = [c.id for c in chapters]
    schema_version = request.schema_version or DREAMWEAVER_SCHEMA_VERSION
    runtime_config = apply_locked_generation_config(
        _build_dreamweaver_runtime_config_from_request(request),
        locked_cfg,
    )
    request_preflight = build_dreamweaver_run_preflight(
        quality_mode=request.quality_mode,
        smart_tuning=request.smart_tuning,
        qc_allow_fail=request.qc_allow_fail,
        video_require_confirmation=request.video_require_confirmation,
        runtime_config=runtime_config,
    )
    _ensure_dreamweaver_request_preflight_passed(request_preflight)
    video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
    video_cfg.update(copy.deepcopy(request_preflight.resolved_video_config))
    runtime_config["video_config"] = video_cfg
    runtime_config["preflight"] = request_preflight.to_dict()
    precheck = build_dreamweaver_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=request.project_id,
        project_title=project.title,
        chapter_rows=chapters,
        chapter_ids=chapter_id_list,
        runtime_config=runtime_config,
        schema_version=schema_version,
    )
    _ensure_dreamweaver_points_precheck_passed(precheck)

    run_id = f"drama_{request.project_id}_{int(time.time())}"
    task_id = str(uuid.uuid4())

    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, result, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :result, :created_at)
        """
    )
    db.execute(
        insert_query,
        {
            "project_id": request.project_id,
            "task_type": "dreamweaver",
            "task_id": task_id,
            "status": "queued",
            "result": json.dumps(
                {
                    "run_id": run_id,
                    "state": "INIT",
                    "stage": "init",
                    "progress": 0,
                    "queue": _dreamweaver_celery_queue(),
                },
                ensure_ascii=False,
            ),
            "created_at": utc_now().isoformat(),
        },
    )
    db.add(
        DreamweaverProjectModel(
            run_id=run_id,
            source_project_id=request.project_id,
            user_id=current_user.id,
            schema_version=schema_version,
            status="queued",
            state="INIT",
            stage="init",
            progress=0,
        )
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_task

    task_args: List[Any] = [task_id, run_id, request.project_id, current_user.id, chapter_id_list, source_text, schema_version]
    if runtime_config:
        task_args.append(runtime_config)

    run_dreamweaver_task.apply_async(args=task_args, queue=_dreamweaver_celery_queue(), task_id=task_id)

    return RunAsyncResponse(
        task_id=task_id,
        run_id=run_id,
        status="queued",
        preflight=request_preflight.to_dict(),
    )

