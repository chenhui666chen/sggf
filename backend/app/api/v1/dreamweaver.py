from __future__ import annotations

import json
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import uuid

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.project import Project, Chapter
from app.models.user import User
from app.models.dreamweaver import DreamweaverProject as DreamweaverProjectModel
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION

from pipeline.state_machine import RunContext, progress_percent, run_until_done, stage_label

router = APIRouter(prefix="/api/v1/dreamweaver", tags=["dreamweaver"])


class MockRunRequest(BaseModel):
    project_id: int
    chapter_ids: List[int] = Field(default_factory=list)
    # 用于版本化契约与资产锚点（可选，默认 0.1.0）
    schema_version: Optional[str] = None


class MockRunResponse(BaseModel):
    run_id: str
    state: str
    stage: Optional[str] = None
    progress: Optional[int] = None
    source_chapter_count: int
    plan: Optional[dict] = None
    storyboard: Optional[list] = None
    keyframes: Optional[list] = None
    midframes: Optional[list] = None
    video_clips: Optional[list] = None
    merged_video: Optional[str] = None
    audit: Optional[dict] = None
    autoqc: Optional[dict] = None


class MockRunAsyncResponse(BaseModel):
    task_id: str
    run_id: str
    status: str


class MockTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    run_id: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    artifacts: Optional[dict] = None
    error_type: Optional[str] = None
    result: Optional[MockRunResponse] = None
    error: Optional[str] = None


def _load_project_chapters(
    db: Session, *, project_id: int, chapter_ids: List[int] | None
) -> List[Chapter]:
    chapter_query = db.query(Chapter).filter(Chapter.project_id == project_id)
    if chapter_ids:
        chapter_query = chapter_query.filter(Chapter.id.in_(chapter_ids))
    return chapter_query.order_by(Chapter.chapter_number.asc()).all()


def _build_source_text(chapters: List[Chapter]) -> str:
    return "\n\n".join(
        [
            f"{c.title or f'第{c.chapter_number}章'}\n{c.content or ''}"
            for c in chapters
        ]
    )


@router.post("/mock-run", response_model=MockRunResponse)
def run_mock_pipeline(
    request: MockRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    织梦映心 Mock 流程：读取灵感方舟项目章节，串行跑通 mock 状态机，返回产物路径与阶段信息。
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="所选项目暂无章节可供导入"
        )

    source_text = "\n\n".join(
        [
            f"{c.title or f'第{c.chapter_number}章'}\n{c.content or ''}"
            for c in chapters
        ]
    )

    run_id = f"drama_{request.project_id}_{int(time.time())}"
    ctx = RunContext(
        run_id=run_id,
        payload={
            "project_id": request.project_id,
            "chapter_ids": [c.id for c in chapters],
            "source_text": source_text,
        },
    )

    ctx = run_until_done(ctx)

    # 同步接口也落库，保持与异步一致（便于后续复现与对比）
    try:
        from app.services.dreamweaver.persistence import build_contract_from_payload, persist_contract

        schema_version = request.schema_version or DREAMWEAVER_SCHEMA_VERSION
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
            status="completed" if ctx.state.name == "DONE" else "failed",
            state=ctx.state.name,
            stage=stage_label(ctx.state),
            progress=progress_percent(ctx.state),
        )
    except Exception:
        # 同步接口不因落库失败而影响体验，错误由日志/DB 侧排查
        pass

    return MockRunResponse(
        run_id=run_id,
        state=ctx.state.name,
        stage=stage_label(ctx.state),
        progress=progress_percent(ctx.state),
        source_chapter_count=len(chapters),
        plan=ctx.payload.get("plan"),
        storyboard=ctx.payload.get("storyboard"),
        keyframes=ctx.payload.get("keyframes"),
        midframes=ctx.payload.get("midframes"),
        video_clips=ctx.payload.get("video_clips"),
        merged_video=ctx.payload.get("merged_video"),
        audit=ctx.payload.get("audit"),
        autoqc=ctx.payload.get("autoqc"),
    )


@router.post("/mock-run-async", response_model=MockRunAsyncResponse)
def run_mock_pipeline_async(
    request: MockRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    织梦映心 Mock 流程（异步）：写入 generation_history 并交给 Celery 执行。
    """
    project = (
        db.query(Project)
        .filter(Project.id == request.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在或无权访问"
        )

    chapters = _load_project_chapters(
        db, project_id=request.project_id, chapter_ids=request.chapter_ids
    )
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="所选项目暂无章节可供导入"
        )

    run_id = f"drama_{request.project_id}_{int(time.time())}"
    task_id = str(uuid.uuid4())

    # 使用 ASCII 兜底，避免编码问题影响 mock 流程。
    source_text = "\n\n".join(
        [
            f"{(c.title or f'Chapter {c.chapter_number}')}\n{(c.content or '')}"
            for c in chapters
        ]
    )
    chapter_id_list = [c.id for c in chapters]

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
            "task_type": "dreamweaver_mock",
            "task_id": task_id,
            "status": "running",
            "result": json.dumps(
                {"run_id": run_id, "state": "INIT", "stage": "init", "progress": 0},
                ensure_ascii=False,
            ),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    db.commit()

    from app.tasks.dreamweaver_tasks import run_dreamweaver_mock_task

    schema_version = request.schema_version or DREAMWEAVER_SCHEMA_VERSION
    run_dreamweaver_mock_task.apply_async(
        args=[task_id, run_id, request.project_id, current_user.id, chapter_id_list, source_text, schema_version],
        queue="audiobook",
        task_id=task_id,
    )

    return MockRunAsyncResponse(task_id=task_id, run_id=run_id, status="running")


@router.get("/task/{task_id}", response_model=MockTaskStatusResponse)
def get_mock_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询织梦映心 Mock 异步任务状态。
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
            status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或无权访问"
        )

    status_str = row[1]
    progress = 50 if status_str == "running" else 100 if status_str == "completed" else 0

    run_id: Optional[str] = None
    state: Optional[str] = None
    stage: Optional[str] = None
    artifacts: Optional[dict] = None
    error_type: Optional[str] = None
    parsed_result: Optional[MockRunResponse] = None
    if row[2]:
        try:
            payload = json.loads(row[2])
            if isinstance(payload, dict):
                run_id = payload.get("run_id")
                state = payload.get("state")
                stage = payload.get("stage")
                artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else None
                error_type = payload.get("error_type") if isinstance(payload.get("error_type"), str) else None
                if isinstance(payload.get("progress"), int):
                    progress = payload["progress"]
                if status_str == "completed" and {"run_id", "state", "source_chapter_count"}.issubset(payload):
                    parsed_result = MockRunResponse(**payload)
        except Exception:
            run_id = None

    return MockTaskStatusResponse(
        task_id=row[0],
        status=status_str,
        progress=progress,
        run_id=run_id,
        state=state,
        stage=stage,
        artifacts=artifacts,
        error_type=error_type,
        result=parsed_result,
        error=row[3],
    )


@router.get("/runs/{run_id}", response_model=dict)
def get_persisted_run_contract(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取已持久化的强类型契约快照（Project/Episode/Shot/Asset）。
    """
    row = (
        db.query(DreamweaverProjectModel)
        .filter(DreamweaverProjectModel.run_id == run_id, DreamweaverProjectModel.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_id 不存在或无权访问")

    return {
        "dreamweaver_project_id": row.id,
        "run_id": row.run_id,
        "status": row.status,
        "state": row.state,
        "stage": row.stage,
        "progress": row.progress,
        "schema_version": row.schema_version,
        "error_type": row.error_type,
        "error_message": row.error_message,
        "contract": row.contract_json,
    }
