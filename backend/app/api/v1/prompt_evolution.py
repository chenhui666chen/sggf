"""
提示词进化系统 API

独立的实验性API，用于自动优化"降低AI痕迹"的提示词
所有优化结果需要人工审核确认后才能使用
"""
import asyncio
from app.services.ai_trace_storage import get_background_optimization_coordinator
from app.core.permissions import require_admin
from typing import Any, Dict, Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
import logging

from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.prompt_evolution import (
    PromptEvolutionEngine,
    EvolutionConfig,
    EvolutionHistory,
    ApprovalStatus,
    PromptVersion
)
from app.services.prompt_evolution.storage import get_evolution_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/prompt-evolution", tags=["Prompt Evolution"])

# 全局状态：正在运行的进化任务
_running_task: Optional[asyncio.Task] = None
_current_evolution_id: Optional[str] = None
# 题材列表单一来源：契约模块常量（与调度 beat 任务共用，新增题材只改契约模块）
from app.services.prompt_evolution.experiment_contract import EVOLUTION_GENRES
_genre_queue_status: Dict[str, Any] = {}


def resolve_evolution_genres(run_all_genres: bool, genre: Optional[str]) -> List[Optional[str]]:
    """解析本次启动需要依次执行的题材。"""
    if run_all_genres:
        return list(EVOLUTION_GENRES)
    return [genre]


def _reset_genre_queue_status(genres: List[Optional[str]]) -> None:
    _genre_queue_status.clear()
    _genre_queue_status.update({
        "active": True,
        "queue_mode": len(genres) > 1,
        "genres": list(genres),
        "current_genre": None,
        "current_index": 0,
        "completed_genres": [],
        "failed_genres": [],
    })


async def _run_genre_evolution_queue(
    genres: List[Optional[str]],
    config: EvolutionConfig,
) -> Dict[str, List[str]]:
    """为每个题材创建独立引擎并顺序执行。"""
    global _current_evolution_id

    try:
        for index, genre in enumerate(genres, start=1):
            display_genre = genre or "通用"
            _genre_queue_status["current_genre"] = display_genre
            _genre_queue_status["current_index"] = index
            engine = PromptEvolutionEngine(config, genre=genre)
            logger.info("开始题材进化队列 %s/%s: %s", index, len(genres), display_genre)
            try:
                evolution_task = asyncio.create_task(engine.run_evolution())
                await asyncio.sleep(0)
                if engine.history:
                    _current_evolution_id = engine.history.evolution_id
                history = await evolution_task
                _current_evolution_id = history.evolution_id
                _genre_queue_status["completed_genres"].append(display_genre)
                logger.info("题材进化完成: %s (%s)", display_genre, history.evolution_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                if engine.history:
                    _current_evolution_id = engine.history.evolution_id
                _genre_queue_status["failed_genres"].append(display_genre)
                logger.exception("题材进化失败，继续下一题材: %s", display_genre)
    finally:
        _genre_queue_status["active"] = False
        _genre_queue_status["current_genre"] = None

    return {
        "completed_genres": list(_genre_queue_status["completed_genres"]),
        "failed_genres": list(_genre_queue_status["failed_genres"]),
    }


# ============================================================================
# 请求/响应模型
# ============================================================================

class StartEvolutionRequest(BaseModel):
    """启动进化请求"""
    target_score: int = Field(default=25, ge=0, le=100, description="目标AI得分阈值")
    max_iterations: int = Field(default=6, ge=1, le=50, description="最大迭代次数")
    samples_per_iteration: int = Field(default=8, ge=1, le=20, description="每次迭代样本数")
    genre: Optional[str] = Field(default=None, description="目标题材；为空时自动检测")
    run_all_genres: bool = Field(default=False, description="按固定顺序优化全部题材")


class ApprovePromptRequest(BaseModel):
    """批准提示词请求"""
    evolution_id: str
    version_id: str


class OptimizeExperiencesRequest(BaseModel):
    """🆕 优化经验请求"""
    genre: Optional[str] = Field(default=None, description="可选的题材过滤")
    force: bool = Field(default=False, description="强制优化（忽略触发条件）")


class OptimizeExperiencesResponse(BaseModel):
    """🆕 优化经验响应"""
    success: bool
    original_count: int
    optimized_count: int
    merged_groups_count: int
    removed_count: int
    summary: str
    message: Optional[str] = None


class EvolutionStatusResponse(BaseModel):
    """进化状态响应"""
    is_running: bool
    evolution_id: Optional[str] = None
    status: Optional[str] = None
    current_iteration: Optional[int] = None
    max_iterations: Optional[int] = None
    best_score: Optional[float] = None
    queue_mode: bool = False
    current_genre: Optional[str] = None
    queue_current: Optional[int] = None
    queue_total: Optional[int] = None
    completed_genres: List[str] = Field(default_factory=list)
    failed_genres: List[str] = Field(default_factory=list)


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
    genre: Optional[str] = None


# ============================================================================
# API 端点
# ============================================================================

@router.post("/start", response_model=EvolutionStatusResponse)
async def start_evolution(
    request: StartEvolutionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin)
):
    """
    启动提示词进化优化（后台运行）

    这是一个实验性功能，优化完成后需要人工审核确认
    """
    global _running_task, _current_evolution_id

    if _running_task and not _running_task.done():
        raise HTTPException(status_code=400, detail="已有进化任务正在运行")
    coordinator = get_background_optimization_coordinator()
    task_lease = coordinator.try_start("prompt_evolution", "自动")
    if task_lease is None:
        raise HTTPException(status_code=409, detail="已有后台优化任务运行中或处于冷却期")

    # 创建配置
    config = EvolutionConfig(
        target_score=request.target_score,
        max_iterations=request.max_iterations,
        samples_per_iteration=request.samples_per_iteration
    )

    genres = resolve_evolution_genres(request.run_all_genres, request.genre)
    _current_evolution_id = None
    _reset_genre_queue_status(genres)

    # 在后台启动进化任务
    async def run_task():
        logger.debug("🚀🚀🚀 [API] 后台任务开始执行...")
        try:
            result = await _run_genre_evolution_queue(genres, config)
            logger.info("进化队列完成: 成功=%s, 失败=%s", result["completed_genres"], result["failed_genres"])
        except asyncio.CancelledError:
            logger.info("进化队列已由管理员停止")
            raise
        finally:
            task_lease.finish(status="failed" if _genre_queue_status["failed_genres"] else "completed")

    logger.debug("🚀 [API] 创建后台任务...")
    _running_task = asyncio.create_task(run_task())
    logger.debug("🚀 [API] 后台任务已创建")

    return EvolutionStatusResponse(
        is_running=True,
        evolution_id=_current_evolution_id,
        status="running",
        current_iteration=0,
        max_iterations=config.max_iterations,
        queue_mode=_genre_queue_status["queue_mode"],
        current_genre=_genre_queue_status["current_genre"],
        queue_current=_genre_queue_status["current_index"],
        queue_total=len(genres),
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
                logger.debug(f"⚠️ 检测到遗留的running状态任务 {running_history['evolution_id']}，已标记为interrupted")
        return EvolutionStatusResponse(
            is_running=is_running,
            queue_mode=bool(_genre_queue_status.get("queue_mode")),
            current_genre=_genre_queue_status.get("current_genre"),
            queue_current=_genre_queue_status.get("current_index"),
            queue_total=len(_genre_queue_status.get("genres", [])) or None,
            completed_genres=_genre_queue_status.get("completed_genres", []),
            failed_genres=_genre_queue_status.get("failed_genres", []),
        )

    storage = get_evolution_storage()
    history = storage.load_evolution_history(_current_evolution_id)

    if not history:
        return EvolutionStatusResponse(is_running=is_running, evolution_id=_current_evolution_id)

    # 如果存储显示running但实际任务已不存在，更新状态
    if history.status == "running" and not is_running:
        history.status = "interrupted"
        storage.save_evolution_history(history)
        logger.debug(f"⚠️ 任务 {_current_evolution_id} 已中断，更新状态")

    best_score = history.best_versions[0].avg_ai_score if history.best_versions else None

    return EvolutionStatusResponse(
        is_running=is_running,
        evolution_id=history.evolution_id,
        status=history.status,
        current_iteration=history.current_iteration,
        max_iterations=history.max_iterations,
        best_score=best_score,
        queue_mode=bool(_genre_queue_status.get("queue_mode")),
        current_genre=_genre_queue_status.get("current_genre"),
        queue_current=_genre_queue_status.get("current_index"),
        queue_total=len(_genre_queue_status.get("genres", [])) or None,
        completed_genres=_genre_queue_status.get("completed_genres", []),
        failed_genres=_genre_queue_status.get("failed_genres", []),
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
                    logger.debug(f"⚠️ 清理遗留running状态: {h['evolution_id']}")

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
        error_message=history.error_message,
        genre=history.genre,
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
                        "error": r.error,
                        "original_multi_score": r.original_multi_score,
                        "rewritten_multi_score": r.rewritten_multi_score,
                        "llm_review": r.llm_review,
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
async def stop_evolution(current_user: User = Depends(require_admin)):
    """停止当前运行的进化任务"""
    global _running_task

    if _running_task and not _running_task.done():
        _running_task.cancel()
        return {"success": True, "message": "进化任务已停止"}

    return {"success": False, "message": "没有正在运行的任务"}


class ResumeRequest(BaseModel):
    """恢复进化请求"""
    evolution_id: str = Field(description="要恢复的进化任务ID")
    additional_iterations: int = Field(default=5, ge=1, le=20, description="额外迭代次数")


@router.post("/resume")
async def resume_evolution(
    request: ResumeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
):
    """
    恢复中断/失败的进化任务

    从上次中断的位置继续进化，使用已有的最佳版本作为起点。
    """
    global _running_task, _current_evolution_id

    if _running_task and not _running_task.done():
        raise HTTPException(status_code=409, detail="已有进化任务在运行中")

    storage = get_evolution_storage()
    history = storage.get_resumable_history(request.evolution_id)
    if not history:
        raise HTTPException(status_code=404, detail="找不到可恢复的进化任务（需为 interrupted 或 failed 状态）")
    coordinator = get_background_optimization_coordinator()
    task_lease = coordinator.try_start("prompt_evolution_resume", history.genre or "通用")
    if task_lease is None:
        raise HTTPException(status_code=409, detail="已有后台优化任务运行中或处于冷却期")

    # 从历史中恢复：使用已完成的迭代数 + 额外迭代
    resume_from_iteration = history.current_iteration
    total_iterations = resume_from_iteration + request.additional_iterations

    config = EvolutionConfig(
        target_score=history.target_score,
        max_iterations=total_iterations,
    )

    engine = PromptEvolutionEngine(config=config, storage=storage)

    # 恢复历史状态
    history.status = "running"
    history.max_iterations = total_iterations
    history.completed_at = None
    history.error_message = None
    engine.history = history
    engine.is_running = True

    # 恢复最佳版本追踪
    if history.best_versions:
        best_v = history.best_versions[0]
        engine.best_ever_version = best_v
        engine.best_ever_score = best_v.avg_composite_score or best_v.avg_ai_score

    _current_evolution_id = history.evolution_id
    storage.save_evolution_history(history)

    async def _run_resumed():
        """从断点继续进化"""
        try:
            # 获取起始提示词（用已有最佳）
            if history.best_versions:
                start_prompt = history.best_versions[0].prompt_text
            elif history.all_versions:
                start_prompt = history.all_versions[-1].prompt_text
            else:
                start_prompt = engine._get_best_starting_prompt()

            # 获取样本
            samples = await engine._prepare_samples_for_evolution()

            # 🆕 改写执行模型对齐该题材的竞争胜出模型（与正常进化路径一致）
            from app.services.ai_trace_competition import MultiModelEvaluationService
            engine.rewrite_model_id = MultiModelEvaluationService().get_active_model_id(engine.genre)
            if engine.rewrite_model_id:
                logger.info(f"🏆 恢复进化改写使用竞争胜出模型: {engine.rewrite_model_id}")

            # 🔧 经验库初始化与正常进化路径一致：预置经验注入 + 历史批次传承
            engine.meta_optimizer.reset_experience()
            historical_reports = storage.get_all_experience_reports()
            if historical_reports:
                loaded_count = engine.meta_optimizer.load_historical_experience(
                    historical_reports, genre=engine.genre or history.genre
                )
                logger.info(f"📚 恢复进化加载历史经验: {loaded_count} 条")

            # 创建当前版本（从上次最佳开始）
            current_version = PromptVersion(prompt_text=start_prompt, iteration=resume_from_iteration)

            # 评估当前版本作为基线
            avg_score, results = await engine.evaluator.evaluate_prompt(
                start_prompt, samples, config.temperature,
                model_id=engine.rewrite_model_id
            )
            current_version.avg_ai_score = avg_score
            current_version.evaluation_results = results

            logger.info(f"🔄 恢复进化: 从迭代 {resume_from_iteration} 继续, 基线分数={avg_score:.1f}")

            # 继续迭代（复用引擎的迭代逻辑 - 简化版）
            from datetime import datetime as dt
            for iteration in range(resume_from_iteration + 1, total_iterations + 1):
                engine.history.current_iteration = iteration

                improved_prompt, analysis = await engine.meta_optimizer.optimize_prompt(
                    current_version, config.target_score, engine.history.all_versions
                )

                new_version = PromptVersion(
                    prompt_text=improved_prompt,
                    iteration=iteration,
                    parent_version_id=current_version.version_id,
                    analysis=analysis,
                )

                avg_score, results = await engine.evaluator.evaluate_prompt(
                    improved_prompt, samples, config.temperature,
                    model_id=engine.rewrite_model_id
                )
                new_version.avg_ai_score = avg_score
                new_version.evaluation_results = results
                new_version.avg_score_reduction = engine._calc_avg_reduction(results)

                engine._update_best_versions(new_version)
                engine.history.all_versions.append(new_version)
                engine._save_progress()

                current_version = new_version
                logger.info(f"  迭代 {iteration}: 得分 {avg_score:.1f}")

            engine.history.status = "completed"
            engine.history.completed_at = dt.now().isoformat()
            engine._save_progress()

            # 保存经验
            experience_report = engine.meta_optimizer.get_experience_report()
            engine._save_experience_report(experience_report)

            logger.info(f"✅ 恢复进化完成: {engine.history.evolution_id}")

        except Exception as e:
            logger.error(f"❌ 恢复进化失败: {e}")
            if engine.history:
                engine.history.status = "failed"
                engine.history.error_message = str(e)
                engine._save_progress()
        finally:
            engine.is_running = False
            task_lease.finish(status="completed" if engine.history.status == "completed" else "failed")

    _running_task = asyncio.ensure_future(_run_resumed())

    return {
        "success": True,
        "message": f"从迭代 {resume_from_iteration} 恢复，将继续 {request.additional_iterations} 轮",
        "evolution_id": history.evolution_id,
        "resume_from": resume_from_iteration,
        "total_iterations": total_iterations,
    }


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


@router.post("/optimize-experiences", response_model=OptimizeExperiencesResponse)
async def optimize_experiences(
    request: OptimizeExperiencesRequest,
    current_user: User = Depends(get_current_user)
):
    """
    🆕 手动触发经验优化

    功能：
    - 语义去重：合并相似的经验
    - 质量过滤：移除低质量经验
    - 效果排序：按出现频率和效果排序
    - 压缩优化：176条 → 30-40条核心经验
    """
    from app.services.prompt_evolution.experience_optimizer import get_experience_optimizer

    storage = get_evolution_storage()
    optimizer = get_experience_optimizer()

    # 获取所有经验报告
    historical_reports = storage.get_all_experience_reports()

    if not historical_reports:
        return OptimizeExperiencesResponse(
            success=False,
            original_count=0,
            optimized_count=0,
            merged_groups_count=0,
            removed_count=0,
            summary="无历史经验报告，无需优化",
            message="请先运行几次提示词进化以积累经验"
        )

    # 检查是否需要优化
    if not request.force:
        metadata = storage.get_optimization_metadata()
        total_reports = len(historical_reports)
        last_opt_count = metadata.get("last_optimization_count", 0)

        if not optimizer.should_trigger_optimization(total_reports, last_opt_count):
            return OptimizeExperiencesResponse(
                success=False,
                original_count=total_reports,
                optimized_count=0,
                merged_groups_count=0,
                removed_count=0,
                summary=f"未达到优化触发条件：当前 {total_reports} 个报告，上次优化 {last_opt_count} 个（需增加≥20或总数>40）",
                message="可使用 force=true 强制优化"
            )

    try:
        logger.info(f"🔧 开始优化经验：共 {len(historical_reports)} 个报告")

        # 执行优化
        opt_result = await optimizer.optimize_experiences(
            historical_reports,
            genre=request.genre
        )

        # 保存优化结果
        optimized_exps = [item.to_dict() for item in opt_result.top_strategies]
        storage.save_optimized_experiences(optimized_exps)
        storage.update_optimization_metadata(len(historical_reports))

        logger.info(f"✅ 经验优化完成: {opt_result.original_count} → {len(opt_result.top_strategies)} 条")

        return OptimizeExperiencesResponse(
            success=True,
            original_count=opt_result.original_count,
            optimized_count=len(opt_result.top_strategies),
            merged_groups_count=len(opt_result.merged_groups),
            removed_count=len(opt_result.removed_low_quality),
            summary=opt_result.optimization_summary,
            message="经验优化成功"
        )

    except Exception as e:
        logger.error(f"❌ 经验优化失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"优化失败: {str(e)}")


@router.get("/optimization-status")
async def get_optimization_status(current_user: User = Depends(get_current_user)):
    """🆕 获取经验优化状态"""
    storage = get_evolution_storage()
    metadata = storage.get_optimization_metadata()
    optimized_data = storage.load_optimized_experiences()
    historical_reports = storage.get_all_experience_reports()

    total_reports = len(historical_reports)
    last_opt_count = metadata.get("last_optimization_count", 0)
    optimized_at = metadata.get("optimized_at")

    # 计算是否应该优化
    from app.services.prompt_evolution.experience_optimizer import get_experience_optimizer
    optimizer = get_experience_optimizer()
    should_optimize = optimizer.should_trigger_optimization(total_reports, last_opt_count)

    return {
        "total_reports": total_reports,
        "last_optimization_count": last_opt_count,
        "new_reports_since_last": total_reports - last_opt_count,
        "optimized_at": optimized_at,
        "has_optimized_data": optimized_data is not None,
        "optimized_experience_count": optimized_data.get("total_count", 0) if optimized_data else 0,
        "should_optimize": should_optimize,
        "optimization_trigger_threshold": "\u589e\u52a0>=20\u4e2a\u62a5\u544a \u6216 \u603b\u6570>40"
    }


# ============================================================================
# 测试样本管理 API
# ============================================================================

class AddSampleRequest(BaseModel):
    """添加自定义测试样本"""
    text: str = Field(min_length=50, max_length=2000, description="样本文本（50-2000字）")
    genre: str = Field(default="其他", description="题材类型")
    description: str = Field(default="", max_length=100, description="样本描述")


@router.get("/samples")
async def get_test_samples(current_user: User = Depends(get_current_user)):
    """获取所有测试样本"""
    from app.services.prompt_evolution.test_samples import get_sample_manager
    manager = get_sample_manager()
    samples = manager.get_all_samples()
    return {
        "success": True,
        "samples": [s.to_dict() for s in samples],
        "summary": manager.get_summary(),
    }


@router.post("/samples")
async def add_test_sample(
    request: AddSampleRequest,
    current_user: User = Depends(get_current_user),
):
    """管理员添加自定义测试样本"""
    import uuid
    from app.services.prompt_evolution.test_samples import (
        get_sample_manager, TestSample, SampleSource
    )
    manager = get_sample_manager()

    sample = TestSample(
        sample_id=f"custom_{uuid.uuid4().hex[:8]}",
        text=request.text.strip(),
        genre=request.genre,
        description=request.description or f"管理员自定义 - {request.genre}",
        source=SampleSource.CUSTOM,
    )
    manager.add_sample(sample)
    return {"success": True, "sample": sample.to_dict()}


@router.delete("/samples/{sample_id}")
async def delete_test_sample(
    sample_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除测试样本"""
    from app.services.prompt_evolution.test_samples import get_sample_manager
    manager = get_sample_manager()
    removed = manager.remove_sample(sample_id)
    if not removed:
        raise HTTPException(status_code=404, detail="样本不存在")
    return {"success": True, "message": "样本已删除"}


@router.post("/samples/generate")
async def generate_test_samples(
    current_user: User = Depends(get_current_user),
):
    """
    使用 LLM 自动生成测试样本

    每种题材生成 2 个样本（共 14 个），替换旧的自动生成样本。
    管理员自定义样本不受影响。
    """
    from app.services.prompt_evolution.test_samples import (
        get_sample_manager, generate_samples_via_llm
    )

    try:
        samples = await generate_samples_via_llm(count_per_genre=2)
        if not samples:
            return {"success": False, "error": "生成失败，未产出有效样本"}

        manager = get_sample_manager()
        manager.add_auto_samples(samples)
        return {
            "success": True,
            "generated_count": len(samples),
            "message": f"成功生成 {len(samples)} 个测试样本",
            "summary": manager.get_summary(),
        }
    except Exception as e:
        logger.error(f"自动生成样本失败: {e}")
        return {"success": False, "error": f"生成失败: {str(e)}"}


# ============================================================================
# 冠军晋升 / 回滚 / 推荐查询 API（设计文档 §8.3 / §10 · §14 第 9 步 · 子块 C）
#
# 第一版不做自动晋升：系统给推荐（GET recommendation）→ 管理员权衡后确认
# （POST promote）→ 原子切换指针。硬闸门（§8.1）不可绕过；如需绕过须显式授权 +
# 填写原因并记入 gate_overridden 审计。回滚以指针表为冠军权威，秒级重指历史版本。
# offline_gate_passed（§8.1 #2）取自挑战者行，不信任客户端。
# ============================================================================

class ChampionRecommendationItem(BaseModel):
    """单个挑战者的晋升评估结果"""
    challenger_id: str
    total: int
    effective_total: int
    confirmed_win: int
    loss: int
    win_rate: float
    wilson_lower_bound: float
    invalidation_rate: float
    hard_fail_rate: float
    hard_gate_passed: bool
    hard_gate_failures: List[str] = Field(default_factory=list)
    recommended: bool
    recommend_failures: List[str] = Field(default_factory=list)


class ChampionRecommendationResponse(BaseModel):
    """晋升推荐查询响应"""
    genre: str
    evaluation_policy_version: str
    count: int
    items: List[ChampionRecommendationItem] = Field(default_factory=list)


class PromoteChampionRequest(BaseModel):
    """晋升执行请求"""
    genre: str
    challenger_id: str
    evaluation_policy_version: str
    light_judge_version: Optional[str] = Field(default=None, description="按评审器版本进一步过滤样本")
    reason: Optional[str] = Field(default=None, description="晋升备注")
    gate_override: bool = Field(default=False, description="是否绕过硬闸门（须填 override_reason）")
    override_reason: Optional[str] = Field(default=None, description="绕过硬闸门的书面理由（§8.1）")


class PromoteChampionResponse(BaseModel):
    """晋升执行响应"""
    promoted: bool
    reason: str
    hard_gate_passed: Optional[bool] = None
    hard_gate_failures: List[str] = Field(default_factory=list)
    recommended: Optional[bool] = None
    recommend_failures: List[str] = Field(default_factory=list)
    prompt_version_id: Optional[str] = None
    previous_version_id: Optional[str] = None


class RollbackChampionRequest(BaseModel):
    """回滚请求"""
    genre: str
    target_version_id: str
    reason: str = Field(description="回滚原因（审计必填）")


class RollbackChampionResponse(BaseModel):
    """回滚响应"""
    success: bool
    reason: str
    prompt_version_id: Optional[str] = None
    previous_version_id: Optional[str] = None


@router.get("/champion/recommendation", response_model=ChampionRecommendationResponse)
async def get_champion_recommendation(
    genre: str,
    evaluation_policy_version: str,
    light_judge_version: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    列出某题材下 returnable 挑战者的晋升评估（硬闸门 + 推荐指标），供管理员决策。

    数据源：returnable 挑战者（prompt_challengers）+ 各自结算 verdict 序列
    （prompt_experiments，按本评审策略版本过滤）+ 挑战者行 offline_gate_passed（§8.1 #2）。
    只读，不改任何状态。
    """
    from app.services.prompt_evolution.challenger_repository import ChallengerRepository
    from app.services.prompt_evolution.experiment_contract import ServingMode
    from app.services.prompt_evolution.experiment_repository import ExperimentRepository
    from app.services.prompt_evolution.promotion import (
        PromotionThresholds,
        aggregate_challenger_stats,
        evaluate_promotion_gate,
    )

    thresholds = PromotionThresholds()
    chal_repo = ChallengerRepository(db)
    exp_repo = ExperimentRepository(db)

    challengers = chal_repo.list_serving(genre, ServingMode.RETURNABLE.value)
    items: List[ChampionRecommendationItem] = []
    for challenger in challengers:
        outcomes = exp_repo.list_outcomes_for_challenger(
            challenger.challenger_id, evaluation_policy_version, light_judge_version
        )
        stats = aggregate_challenger_stats(outcomes, z=thresholds.wilson_z)
        gate = evaluate_promotion_gate(
            stats,
            offline_gate_passed=bool(challenger.offline_gate_passed),
            policy_version_consistent=True,
            has_unresolved_safety_incident=False,
            thresholds=thresholds,
        )
        items.append(
            ChampionRecommendationItem(
                challenger_id=challenger.challenger_id,
                total=stats.total,
                effective_total=stats.effective_total,
                confirmed_win=stats.confirmed_win,
                loss=stats.loss,
                win_rate=stats.win_rate,
                wilson_lower_bound=stats.wilson_lower_bound,
                invalidation_rate=stats.invalidation_rate,
                hard_fail_rate=stats.hard_fail_rate,
                hard_gate_passed=gate.hard_gate_passed,
                hard_gate_failures=list(gate.hard_gate_failures),
                recommended=gate.recommended,
                recommend_failures=list(gate.recommend_failures),
            )
        )

    return ChampionRecommendationResponse(
        genre=genre,
        evaluation_policy_version=evaluation_policy_version,
        count=len(items),
        items=items,
    )


@router.post("/champion/promote", response_model=PromoteChampionResponse)
async def promote_champion_endpoint(
    request: PromoteChampionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    管理员确认晋升某挑战者为冠军（§8.3 原子切换指针）。

    offline_gate_passed（§8.1 #2）取自挑战者行，不信任客户端；operator 取登录管理员。
    硬闸门未过且未授权绕过时返回 promoted=False + 失败项（HTTP 200，供前端展示）；
    绕过须填 override_reason，缺失则 400。
    """
    from app.services.prompt_evolution.challenger_repository import ChallengerRepository
    from app.services.prompt_evolution.champion_promotion import promote_champion

    challenger = ChallengerRepository(db).get_by_challenger_id(request.challenger_id)
    offline_gate_passed = bool(challenger.offline_gate_passed) if challenger is not None else False

    try:
        outcome = promote_champion(
            db,
            genre=request.genre,
            challenger_id=request.challenger_id,
            evaluation_policy_version=request.evaluation_policy_version,
            operator=current_user.username,
            offline_gate_passed=offline_gate_passed,
            light_judge_version=request.light_judge_version,
            reason=request.reason,
            gate_override=request.gate_override,
            override_reason=request.override_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    gate = outcome.gate_result
    assignment = outcome.assignment
    return PromoteChampionResponse(
        promoted=outcome.promoted,
        reason=outcome.reason,
        hard_gate_passed=gate.hard_gate_passed if gate is not None else None,
        hard_gate_failures=list(gate.hard_gate_failures) if gate is not None else [],
        recommended=gate.recommended if gate is not None else None,
        recommend_failures=list(gate.recommend_failures) if gate is not None else [],
        prompt_version_id=assignment.prompt_version_id if assignment is not None else None,
        previous_version_id=assignment.previous_version_id if assignment is not None else None,
    )


@router.post("/champion/rollback", response_model=RollbackChampionResponse)
async def rollback_champion_endpoint(
    request: RollbackChampionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    回滚冠军到历史版本（§8.3 秒级回滚）：指针表为权威，重指目标版本 + 降级当前冠军挑战者。

    目标版本须在该题材指针历史中出现过；未找到返回 404。operator 取登录管理员。
    """
    from app.services.prompt_evolution.champion_promotion import rollback_champion

    outcome = rollback_champion(
        db,
        genre=request.genre,
        target_version_id=request.target_version_id,
        operator=current_user.username,
        reason=request.reason,
    )
    if not outcome.success:
        raise HTTPException(status_code=404, detail="回滚目标版本不在该题材指针历史中")

    assignment = outcome.assignment
    return RollbackChampionResponse(
        success=outcome.success,
        reason=outcome.reason,
        prompt_version_id=assignment.prompt_version_id if assignment is not None else None,
        previous_version_id=assignment.previous_version_id if assignment is not None else None,
    )


class ApproveReturnableRequest(BaseModel):
    """returnable 人工开闸请求"""
    reason: str = Field(
        min_length=1, max_length=500, description="审批原因（审计必填，纯空白拒绝）"
    )

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        # 五轮评审④：与服务层共用同一规则（strip + 拒纯空白 + 换行规范化为空格
        # + 上限对齐审计表 String(500)），ValueError 由 Pydantic 转 422
        from app.services.prompt_evolution.returnable_service import (
            normalize_approval_reason,
        )

        return normalize_approval_reason(value)


class ApproveReturnableResponse(BaseModel):
    """returnable 人工开闸响应"""
    challenger_id: str
    genre: str
    serving_mode: str


@router.post(
    "/challengers/{challenger_id}/returnable", response_model=ApproveReturnableResponse
)
async def approve_returnable_endpoint(
    challenger_id: str,
    request: ApproveReturnableRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    管理员人工开闸（§5.4 / §14 第 8 步）：批准 eligible 挑战者进入 returnable，
    使其参与 best-of-2 择优返回。状态经 serving_mode 状态机校验（§3.1），
    非 eligible 拒绝；operator 取登录管理员，审批 operator + reason 与状态
    变更同事务落审计表（prompt_challenger_state_transitions）。
    """
    from app.services.prompt_evolution.returnable_service import approve_returnable

    try:
        row = approve_returnable(
            db, challenger_id, operator=current_user.username, reason=request.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if row is None:
        raise HTTPException(status_code=404, detail="挑战者不存在")
    return ApproveReturnableResponse(
        challenger_id=row.challenger_id,
        genre=row.genre,
        serving_mode=row.serving_mode,
    )


# ============================================================================
# 进化调度器状态面板 / 手动休眠唤醒 API（设计文档 §11 · §14 第 10 步 · 子块 C）
#
# 只读快照 + 管理员手动干预调度器三态（running/sleeping/awake）。休眠置 sleeping
# （只停离线生成新变体，成对实验监控与择优照常）；唤醒置 awake（过渡态，下一次
# beat tick 消费后转 running 触发定向进化，§11 三态语义）。均只读写 scheduler_state.json
# 落盘账本，不触 DB、不接外部 API。为可测性把状态账本装配为可注入依赖。
# ============================================================================

def get_scheduler_state_store():
    """调度器状态账本依赖（默认落盘 data/prompt_evolution/scheduler_state.json）。"""
    from app.services.prompt_evolution.scheduler_state import SchedulerStateStore
    return SchedulerStateStore()


def get_holdout_score_store():
    """holdout 分差缓存依赖（信号 2 观测，默认落盘 data/prompt_evolution）。"""
    from app.services.prompt_evolution.holdout_probe import HoldoutScoreStore
    return HoldoutScoreStore()


def get_sentinel_state_store():
    """哨兵状态缓存依赖（信号 5 观测，默认落盘 data/prompt_evolution）。"""
    from app.services.prompt_evolution.sentinel_probe import SentinelStateStore
    return SentinelStateStore()


class HoldoutSignalInfo(BaseModel):
    """holdout 分差信号观测（信号 2）：gap 为 tick 真实消费值（含降级）"""
    gap: float
    computed_at: Optional[str] = None
    stale: bool = False
    defaulted: bool = True


class SentinelSignalInfo(BaseModel):
    """哨兵退化信号观测（信号 5）：degraded 为 tick 真实消费值（含降级）"""
    degraded: bool
    checked_at: Optional[str] = None
    stale: bool = False
    defaulted: bool = True


class SchedulerSignals(BaseModel):
    """题材级启停信号观测元数据（纯读缓存组装，defaulted=True 表示消费的是降级默认值）"""
    holdout: HoldoutSignalInfo
    sentinel: SentinelSignalInfo


class SchedulerStateItem(BaseModel):
    """单个题材的调度器三态记录"""
    genre: str
    state: str
    reasons: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = None
    last_tick_at: Optional[str] = None
    signals: Optional[SchedulerSignals] = None


class SchedulerStateSnapshotResponse(BaseModel):
    """调度器状态快照响应（供管理面板）"""
    count: int
    items: List[SchedulerStateItem] = Field(default_factory=list)


class SchedulerManualRequest(BaseModel):
    """手动休眠/唤醒请求"""
    genre: str = Field(description="目标题材（须为已知题材）")
    reason: Optional[str] = Field(default=None, description="手动操作备注（并入 reasons）")


class SchedulerManualResponse(BaseModel):
    """手动休眠/唤醒响应"""
    genre: str
    state: str
    reasons: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = None
    last_tick_at: Optional[str] = None


def _scheduler_record_to_item(record, signals: Optional[SchedulerSignals] = None) -> SchedulerStateItem:
    return SchedulerStateItem(
        genre=record.genre,
        state=record.state,
        reasons=list(record.reasons),
        updated_at=record.updated_at,
        last_tick_at=record.last_tick_at,
        signals=signals,
    )


@router.get("/scheduler/state", response_model=SchedulerStateSnapshotResponse)
async def get_scheduler_state(
    current_user: User = Depends(require_admin),
    store=Depends(get_scheduler_state_store),
    holdout_store=Depends(get_holdout_score_store),
    sentinel_store=Depends(get_sentinel_state_store),
):
    """
    调度器三态快照（§11）：按 EVOLUTION_GENRES 逐题材读取，无记录默认 running。

    只读，不改任何状态；供管理面板观测各题材休眠/唤醒状态与最近 tick 时间。
    每题材附 signals 观测元数据（holdout 信号 2 / 哨兵信号 5）：值为 tick 真实
    消费口径（含降级），defaulted 区分真实信号与降级默认值，纯读缓存不触发外部调用。
    """
    from app.services.prompt_evolution.experiment_contract import (
        EXPERIMENT_EVALUATION_POLICY_VERSION,
    )

    items = []
    for genre in EVOLUTION_GENRES:
        signals = SchedulerSignals(
            holdout=HoldoutSignalInfo(
                **holdout_store.describe_signal(genre, policy=EXPERIMENT_EVALUATION_POLICY_VERSION)
            ),
            sentinel=SentinelSignalInfo(
                **sentinel_store.describe_signal(genre, policy=EXPERIMENT_EVALUATION_POLICY_VERSION)
            ),
        )
        items.append(_scheduler_record_to_item(store.get(genre), signals=signals))
    return SchedulerStateSnapshotResponse(count=len(items), items=items)


@router.post("/scheduler/sleep", response_model=SchedulerManualResponse)
async def sleep_scheduler(
    request: SchedulerManualRequest,
    current_user: User = Depends(require_admin),
    store=Depends(get_scheduler_state_store),
):
    """管理员手动休眠某题材（置 sleeping）；未知题材返回 400。"""
    from datetime import datetime, timezone
    from app.services.prompt_evolution.evolution_scheduler import STATE_SLEEPING

    if request.genre not in EVOLUTION_GENRES:
        raise HTTPException(status_code=400, detail="未知题材")

    reasons = ["manual_sleep"] + ([request.reason] if request.reason else [])
    record = store.set(
        request.genre,
        STATE_SLEEPING,
        reasons=reasons,
        now=datetime.now(timezone.utc).isoformat(),
    )
    return _scheduler_record_to_item(record).model_dump()


@router.post("/scheduler/wake", response_model=SchedulerManualResponse)
async def wake_scheduler(
    request: SchedulerManualRequest,
    current_user: User = Depends(require_admin),
    store=Depends(get_scheduler_state_store),
):
    """
    管理员手动唤醒某题材（置 awake）；未知题材返回 400。

    awake 为过渡态：下一次 beat tick 消费后转 running 重启进化（§11 三态）。
    """
    from datetime import datetime, timezone
    from app.services.prompt_evolution.evolution_scheduler import STATE_AWAKE

    if request.genre not in EVOLUTION_GENRES:
        raise HTTPException(status_code=400, detail="未知题材")

    reasons = ["manual_wake"] + ([request.reason] if request.reason else [])
    record = store.set(
        request.genre,
        STATE_AWAKE,
        reasons=reasons,
        now=datetime.now(timezone.utc).isoformat(),
    )
    return _scheduler_record_to_item(record).model_dump()
