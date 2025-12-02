"""
提示词进化系统 API

独立的实验性API，用于自动优化"降低AI痕迹"的提示词
所有优化结果需要人工审核确认后才能使用
"""
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import logging

from app.core.security import get_current_user
from app.models.user import User
from app.services.prompt_evolution import (
    PromptEvolutionEngine,
    EvolutionConfig,
    EvolutionHistory,
    ApprovalStatus
)
from app.services.prompt_evolution.storage import get_evolution_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/prompt-evolution", tags=["Prompt Evolution"])

# 全局状态：正在运行的进化任务
_running_task: Optional[asyncio.Task] = None
_current_evolution_id: Optional[str] = None


# ============================================================================
# 请求/响应模型
# ============================================================================

class StartEvolutionRequest(BaseModel):
    """启动进化请求"""
    target_score: int = Field(default=30, ge=0, le=100, description="目标AI得分阈值")
    max_iterations: int = Field(default=10, ge=1, le=50, description="最大迭代次数")
    samples_per_iteration: int = Field(default=3, ge=1, le=10, description="每次迭代样本数")


class ApprovePromptRequest(BaseModel):
    """批准提示词请求"""
    evolution_id: str
    version_id: str


class EvolutionStatusResponse(BaseModel):
    """进化状态响应"""
    is_running: bool
    evolution_id: Optional[str] = None
    status: Optional[str] = None
    current_iteration: Optional[int] = None
    max_iterations: Optional[int] = None
    best_score: Optional[float] = None


class PromptVersionSummary(BaseModel):
    """提示词版本摘要"""
    version_id: str
    iteration: int
    avg_ai_score: float
    avg_score_reduction: float
    analysis: str
    created_at: str


class EvolutionDetailResponse(BaseModel):
    """进化详情响应"""
    evolution_id: str
    status: str
    target_score: int
    current_iteration: int
    max_iterations: int
    approval_status: str
    approved_version_id: Optional[str] = None
    best_versions: List[PromptVersionSummary]
    started_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


# ============================================================================
# API 端点
# ============================================================================

@router.post("/start", response_model=EvolutionStatusResponse)
async def start_evolution(
    request: StartEvolutionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    启动提示词进化优化（后台运行）
    
    这是一个实验性功能，优化完成后需要人工审核确认
    """
    global _running_task, _current_evolution_id
    
    if _running_task and not _running_task.done():
        raise HTTPException(status_code=400, detail="已有进化任务正在运行")
    
    # 创建配置
    config = EvolutionConfig(
        target_score=request.target_score,
        max_iterations=request.max_iterations,
        samples_per_iteration=request.samples_per_iteration
    )
    
    # 创建引擎
    engine = PromptEvolutionEngine(config)
    
    # 在后台启动进化任务
    async def run_task():
        global _current_evolution_id
        print("🚀🚀🚀 [API] 后台任务开始执行...")
        try:
            history = await engine.run_evolution()
            _current_evolution_id = history.evolution_id
            print(f"✅✅✅ [API] 进化任务完成: {history.evolution_id}")
            logger.info(f"✅ 进化任务完成: {history.evolution_id}")
        except Exception as e:
            print(f"❌❌❌ [API] 进化任务失败: {e}")
            logger.error(f"❌ 进化任务失败: {e}")
            import traceback
            traceback.print_exc()

    print("🚀 [API] 创建后台任务...")
    _running_task = asyncio.create_task(run_task())
    print("🚀 [API] 后台任务已创建")
    
    # 等待任务开始并获取ID
    await asyncio.sleep(0.5)
    if engine.history:
        _current_evolution_id = engine.history.evolution_id
    
    return EvolutionStatusResponse(
        is_running=True,
        evolution_id=_current_evolution_id,
        status="running",
        current_iteration=0,
        max_iterations=config.max_iterations
    )


@router.get("/status", response_model=EvolutionStatusResponse)
async def get_evolution_status(current_user: User = Depends(get_current_user)):
    """获取当前进化任务状态"""
    global _running_task, _current_evolution_id

    is_running = _running_task is not None and not _running_task.done()

    if not _current_evolution_id:
        # 没有当前任务ID，尝试查找是否有running状态的历史任务
        storage = get_evolution_storage()
        histories = storage.list_evolution_histories()
        running_history = next((h for h in histories if h.get("status") == "running"), None)
        if running_history and not is_running:
            # 有running状态的历史但实际没有任务在跑，更新状态为interrupted
            history_obj = storage.load_evolution_history(running_history["evolution_id"])
            if history_obj:
                history_obj.status = "interrupted"
                storage.save_evolution_history(history_obj)
                print(f"⚠️ 检测到遗留的running状态任务 {running_history['evolution_id']}，已标记为interrupted")
        return EvolutionStatusResponse(is_running=is_running)

    storage = get_evolution_storage()
    history = storage.load_evolution_history(_current_evolution_id)

    if not history:
        return EvolutionStatusResponse(is_running=is_running, evolution_id=_current_evolution_id)

    # 如果存储显示running但实际任务已不存在，更新状态
    if history.status == "running" and not is_running:
        history.status = "interrupted"
        storage.save_evolution_history(history)
        print(f"⚠️ 任务 {_current_evolution_id} 已中断，更新状态")

    best_score = history.best_versions[0].avg_ai_score if history.best_versions else None

    return EvolutionStatusResponse(
        is_running=is_running,
        evolution_id=history.evolution_id,
        status=history.status,
        current_iteration=history.current_iteration,
        max_iterations=history.max_iterations,
        best_score=best_score
    )


@router.get("/history", response_model=List[dict])
async def list_evolution_histories(current_user: User = Depends(get_current_user)):
    """列出所有进化历史"""
    global _running_task, _current_evolution_id

    storage = get_evolution_storage()
    histories = storage.list_evolution_histories()

    # 检测并清理遗留的 running 状态
    is_actually_running = _running_task is not None and not _running_task.done()

    for h in histories:
        if h.get("status") == "running":
            # 如果这个任务显示running，但实际没有任务在跑（或不是当前任务），标记为interrupted
            if not is_actually_running or h.get("evolution_id") != _current_evolution_id:
                history_obj = storage.load_evolution_history(h["evolution_id"])
                if history_obj:
                    history_obj.status = "interrupted"
                    storage.save_evolution_history(history_obj)
                    h["status"] = "interrupted"
                    print(f"⚠️ 清理遗留running状态: {h['evolution_id']}")

    return histories


@router.delete("/history/{evolution_id}")
async def delete_evolution_history(
    evolution_id: str,
    current_user: User = Depends(get_current_user)
):
    """删除指定的进化历史"""
    global _running_task, _current_evolution_id

    # 不能删除正在运行的任务
    if evolution_id == _current_evolution_id and _running_task and not _running_task.done():
        raise HTTPException(status_code=400, detail="不能删除正在运行的任务")

    storage = get_evolution_storage()
    success = storage.delete_evolution_history(evolution_id)

    if not success:
        raise HTTPException(status_code=404, detail="进化记录不存在")

    return {"message": "删除成功", "evolution_id": evolution_id}


@router.post("/history/cleanup")
async def cleanup_evolution_histories(
    keep_recent: int = 10,
    keep_best: int = 5,
    current_user: User = Depends(get_current_user)
):
    """
    自动清理历史记录

    保留规则：
    - 保留最近 keep_recent 个历史（默认10个）
    - 保留得分最好的 keep_best 个历史（默认5个）
    - 保留已批准的历史
    - 保留正在运行的历史
    """
    storage = get_evolution_storage()
    deleted_count = storage.cleanup_histories(keep_recent=keep_recent, keep_best=keep_best)

    return {
        "message": f"清理完成，删除 {deleted_count} 个历史记录",
        "deleted_count": deleted_count
    }


@router.get("/history/{evolution_id}", response_model=EvolutionDetailResponse)
async def get_evolution_detail(
    evolution_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取进化详情（包含最佳提示词版本）"""
    storage = get_evolution_storage()
    history = storage.load_evolution_history(evolution_id)

    if not history:
        raise HTTPException(status_code=404, detail="进化记录不存在")
    
    return EvolutionDetailResponse(
        evolution_id=history.evolution_id,
        status=history.status,
        target_score=history.target_score,
        current_iteration=history.current_iteration,
        max_iterations=history.max_iterations,
        approval_status=history.approval_status.value,
        approved_version_id=history.approved_version_id,
        best_versions=[
            PromptVersionSummary(
                version_id=v.version_id,
                iteration=v.iteration,
                avg_ai_score=v.avg_ai_score,
                avg_score_reduction=v.avg_score_reduction,
                analysis=v.analysis,
                created_at=v.created_at
            )
            for v in history.best_versions
        ],
        started_at=history.started_at,
        completed_at=history.completed_at,
        error_message=history.error_message
    )


@router.get("/history/{evolution_id}/prompt/{version_id}")
async def get_prompt_detail(
    evolution_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取特定版本的完整提示词内容"""
    storage = get_evolution_storage()
    history = storage.load_evolution_history(evolution_id)

    if not history:
        raise HTTPException(status_code=404, detail="进化记录不存在")

    # 在所有版本中查找
    for v in history.best_versions:
        if v.version_id == version_id:
            return {
                "version_id": v.version_id,
                "iteration": v.iteration,
                "prompt_text": v.prompt_text,
                "avg_ai_score": v.avg_ai_score,
                "avg_score_reduction": v.avg_score_reduction,
                "analysis": v.analysis,
                "evaluation_results": [
                    {
                        "sample_id": r.sample_id,
                        "original_ai_score": r.original_ai_score,
                        "rewritten_ai_score": r.rewritten_ai_score,
                        "score_reduction": r.score_reduction,
                        "original_text": r.original_text,
                        "rewritten_text": r.rewritten_text,
                        "success": r.success,
                        "error": r.error
                    }
                    for r in v.evaluation_results
                ],
                "created_at": v.created_at
            }

    raise HTTPException(status_code=404, detail="提示词版本不存在")


@router.post("/approve")
async def approve_prompt(
    request: ApprovePromptRequest,
    current_user: User = Depends(get_current_user)
):
    """
    批准某个版本的提示词

    批准后，该提示词可以被应用到生产环境
    """
    storage = get_evolution_storage()
    success = storage.approve_prompt(request.version_id, request.evolution_id)

    if not success:
        raise HTTPException(status_code=400, detail="批准失败，请检查版本ID")

    return {
        "success": True,
        "message": f"提示词 {request.version_id} 已批准",
        "evolution_id": request.evolution_id,
        "version_id": request.version_id
    }


@router.post("/revoke")
async def revoke_approval(
    request: ApprovePromptRequest,
    current_user: User = Depends(get_current_user)
):
    """
    取消批准某个版本的提示词
    """
    storage = get_evolution_storage()
    success = storage.revoke_approval(request.version_id, request.evolution_id)

    if not success:
        raise HTTPException(status_code=400, detail="取消批准失败，该版本可能未被批准")

    return {
        "success": True,
        "message": f"提示词 {request.version_id} 已取消批准",
        "evolution_id": request.evolution_id,
        "version_id": request.version_id
    }


@router.get("/approved")
async def get_approved_prompts(current_user: User = Depends(get_current_user)):
    """获取所有已批准的提示词列表"""
    storage = get_evolution_storage()
    approved_list = storage.get_all_approved_prompts()
    latest = approved_list[-1] if approved_list else None

    return {
        "approved_prompts": approved_list,
        "count": len(approved_list),
        "latest_approved": latest,
        "message": "已批准的提示词可以应用到生产环境" if latest else "暂无已批准的提示词"
    }


@router.delete("/approved/{version_id}")
async def remove_approved_prompt(
    version_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    从已批准列表中移除指定版本的提示词（不影响进化历史记录）
    """
    storage = get_evolution_storage()
    success = storage.remove_approved_prompt(version_id)

    if not success:
        raise HTTPException(status_code=404, detail="该版本未在已批准列表中")

    return {
        "success": True,
        "message": f"提示词 {version_id} 已从批准列表中移除",
        "version_id": version_id
    }


@router.get("/best-prompts")
async def get_best_prompts(current_user: User = Depends(get_current_user)):
    """获取当前最佳的提示词列表（前5名）"""
    storage = get_evolution_storage()
    best_prompts = storage.load_best_prompts()

    return {
        "count": len(best_prompts),
        "prompts": [
            {
                "version_id": v.version_id,
                "iteration": v.iteration,
                "avg_ai_score": v.avg_ai_score,
                "prompt_preview": v.prompt_text[:200] + "..." if len(v.prompt_text) > 200 else v.prompt_text,
                "created_at": v.created_at
            }
            for v in best_prompts
        ]
    }


@router.post("/stop")
async def stop_evolution(current_user: User = Depends(get_current_user)):
    """停止当前运行的进化任务"""
    global _running_task

    if _running_task and not _running_task.done():
        _running_task.cancel()
        return {"success": True, "message": "进化任务已停止"}

    return {"success": False, "message": "没有正在运行的任务"}


@router.get("/experience/{evolution_id}")
async def get_experience_report(
    evolution_id: str,
    current_user: User = Depends(get_current_user)
):
    """获取指定进化任务的经验报告"""
    storage = get_evolution_storage()
    report = storage.load_experience_report(evolution_id)

    if not report:
        raise HTTPException(status_code=404, detail="经验报告不存在")

    return report


@router.get("/experience")
async def get_all_experience_reports(current_user: User = Depends(get_current_user)):
    """获取所有经验报告"""
    storage = get_evolution_storage()
    reports = storage.get_all_experience_reports()

    return {
        "count": len(reports),
        "reports": reports
    }

