"""
AI痕迹降低 API

提供：
1. /reduce - 用户端降低AI痕迹（使用管理员选定或自动最优模型）
2. /evaluate-models - 管理员多模型评测（提示词进化系统用）
3. /model-config - 模型配置管理（查看/设置活跃模型）
4. /available-models - 查看可用模型及其表现
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.orm import Session
import time
import uuid

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.tencent_ai_detect import tencent_ai_detect_service
from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.storage import EvolutionStorage
from app.services.prompt_evolution.genre_detector import GenreDetector
from app.services.prompt_evolution.genre import normalize_genre
from app.core.permissions import require_admin
from app.services.ai_trace_competition import get_multi_model_service
from app.services.ai_trace_storage import get_background_optimization_coordinator

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai-trace", tags=["AI Trace"])


# ============================================================================
# 用户端：降低AI痕迹（单模型，使用活跃模型）
# ============================================================================

class ReduceRequest(BaseModel):
    """降低AI浓度请求"""
    text: str
    intensity: Optional[str] = "medium"  # light, medium, strong
    original_ai_score: Optional[int] = None
    genre: Optional[str] = None  # 题材（None=自动检测）
    source: Optional[str] = None  # 来源：inspiration_ark / paste / None


class ReduceResponse(BaseModel):
    """降低AI浓度响应"""
    success: bool
    reduced_text: Optional[str] = None
    original_ai_score: Optional[int] = None
    new_ai_score: Optional[int] = None
    label: Optional[str] = None
    improvement: Optional[int] = None
    model_used: Optional[str] = None  # 使用的模型名称
    genre_detected: Optional[str] = None  # 自动检测到的题材
    prompt_version_id: Optional[str] = None
    selection_source: Optional[str] = None
    returned_variant: Optional[str] = None  # returnable 择优返回的变体（champion/challenger），未评估为 None
    error: Optional[str] = None


@router.post("/reduce", response_model=ReduceResponse)
async def reduce_ai_trace(
    request: ReduceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    降低文本的AI痕迹

    使用管理员选定的模型或自动最优模型进行改写。
    模型来源：管理员手动选定 > 进化系统自动择优 > 默认路由。
    """
    text = request.text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="请提供待处理的文本内容")

    if len(text) < 50:
        raise HTTPException(status_code=400, detail="文本过短，请提供至少50个字符")

    if len(text) > 10000:
        logger.warning(f"文本过长 ({len(text)} 字符)，截取前 10000 字符进行处理")
        text = text[:10000]

    # 获取活跃模型（按题材选择最优）
    service = get_multi_model_service()

    # 确定题材：用户指定 > 自动检测
    if request.genre:
        detected_genre = normalize_genre(request.genre)
    else:
        detector = GenreDetector()
        detected_genre = normalize_genre(detector.detect(text))

    active_model_id = service.get_active_model_id(detected_genre)
    model_name = None
    if active_model_id:
        from app.services.ai_trace_competition import _MODEL_INFO_MAP
        info = _MODEL_INFO_MAP.get(active_model_id)
        model_name = info.name if info else active_model_id

    logger.info(
        f"开始降低AI痕迹: 文本长度={len(text)}, 强度={request.intensity}, "
        f"题材={detected_genre}, 活跃模型={model_name or '默认路由'}"
    )
    start_time = time.time()

    try:
        # 1. 检测原始AI分数
        if request.original_ai_score is not None:
            original_score = request.original_ai_score
            logger.info(f"  使用前端已检测分数: {original_score}")
        else:
            step1_start = time.time()
            original_detect_result = await tencent_ai_detect_service.detect_ai_content(text)
            original_score = (
                original_detect_result.get("ai_score", 50)
                if original_detect_result.get("success")
                else 50
            )
            logger.info(f"  原始检测完成: {original_score}分, 耗时={time.time() - step1_start:.2f}秒")

        # 2. 获取优化后的提示词
        meta_optimizer = MetaOptimizer()
        storage = EvolutionStorage()

        selection = storage.get_prompt_selection(detected_genre)

        def get_optimized_prompt() -> str:
            if selection:
                logger.info(f"使用题材「{detected_genre}」匹配的进化提示词")
                return selection["prompt_text"]
            logger.info(f"使用题材「{detected_genre}」初始提示词")
            return meta_optimizer.get_initial_prompt(genre=detected_genre)

        optimized_prompt = get_optimized_prompt()

        # 管理员全局选定拥有最高优先级；自动模式下优先使用与当前提示词联合验证过的模型。
        model_config = service.get_model_config(detected_genre)
        selection_source = "admin_selected" if model_config.get("admin_selected_model") else "genre_model_summary"
        if not model_config.get("admin_selected_model"):
            combination = (
                service.get_best_model_for_prompt_version(detected_genre, selection["version_id"])
                if selection else None
            )
            if combination:
                active_model_id = combination.model_id
                model_name = combination.model_name
                selection_source = "prompt_combination"

        output_requirements = (
            "【输出要求】\n"
            "只输出改写后的文本，保持原文段落结构，不要任何解释、标题或列表。"
        )

        def ensure_output_requirements(prompt_text: str) -> str:
            if "只输出改写后的文本" in prompt_text:
                return prompt_text
            return f"{prompt_text}\n\n{output_requirements}"

        base_intensity_prompts = {
            "light": (
                "请对以下文本进行轻微润色，保持原意不变的前提下，做小幅表达优化，"
                "使其更自然、更像人类写作。\n\n【改写范围】\n"
                "1. 仅做措辞、语序、节奏、标点的轻微调整\n"
                "2. 不增删关键事实，不改变叙述视角\n"
                "3. 尽量保持原文段落结构"
            ),
            "medium": optimized_prompt,
            "strong": f"""{optimized_prompt}

【深度改写附加要求】
1. 彻底重构句式，避免常见的对称结构
2. 替换常见的模板化连接词（如"首先/其次/总之"等）
3. 增加口语化表达与个体化视角
4. 打破段落过度规整，制造更自然的阅读节奏
5. 加入适当语气词与转折停顿
6. 保持核心意思不变，但用完全不同的方式表达
改写后的文本应读起来像是一位有经验的人类作者写的"""
        }

        base_prompt = base_intensity_prompts.get(request.intensity, base_intensity_prompts["medium"])
        prompt = ensure_output_requirements(base_prompt)

        # 3. 调用改写（使用活跃模型）
        evaluator = PromptEvaluator()
        step2_start = time.time()
        reduced_text = await evaluator._rewrite_text(
            prompt, text, temperature=0.8, model_id=active_model_id
        )
        logger.info(
            f"  LLM改写完成: 耗时={time.time() - step2_start:.2f}秒, "
            f"输出长度={len(reduced_text)}字符"
        )

        # 4. 检测改写后AI分数
        step3_start = time.time()
        new_result = await tencent_ai_detect_service.detect_ai_content(reduced_text)
        new_score = (
            new_result.get("ai_score", original_score)
            if new_result.get("success")
            else original_score
        )
        logger.info(f"  改写后检测: {new_score}分, 耗时={time.time() - step3_start:.2f}秒")

        improvement = original_score - new_score
        total_time = time.time() - start_time

        logger.info(
            f"AI痕迹降低完成: {original_score} → {new_score} "
            f"(降低{improvement}分), 总耗时={total_time:.2f}秒, 模型={model_name or '默认'}"
        )

        prompt_version_id = selection["version_id"] if selection else f"initial-{detected_genre}"

        # 旁路：shadow 实验分流（EXPERIMENT_ENABLED 默认关闭；任何异常静默跳过，绝不影响冠军返回）
        try:
            from app.services.prompt_evolution.experiment_contract import FrozenModelContract
            from app.services.prompt_evolution.shadow_dispatch import (
                ShadowDispatchConfig,
                maybe_create_shadow_experiment,
            )

            dispatch_config = ShadowDispatchConfig.from_env()
            if dispatch_config.enabled:
                maybe_create_shadow_experiment(
                    db,
                    subject_id=str(current_user.id),
                    genre=detected_genre,
                    request_id=f"req_{uuid.uuid4().hex[:16]}",
                    original_text=text,
                    champion_text=reduced_text,
                    original_ai_score=original_score,
                    champion_ai_score=new_score,
                    champion_prompt_text=prompt,
                    contract=FrozenModelContract.freeze(
                        resolved_model_id=active_model_id or "default_route",
                        model_selection_source=selection_source,
                        model_config_version=None,
                        prompt_version_id=prompt_version_id,
                        temperature=0.8,
                    ),
                    config=dispatch_config,
                )
        except Exception as dispatch_error:  # noqa: BLE001 —— 旁路红线：只记类型不落原文
            logger.warning(f"shadow 分流旁路异常跳过: {type(dispatch_error).__name__}")

        # 旁路：returnable best-of-2 择优（§5.4 / §14 第 8 步 · 子块 C）
        # EXPERIMENT_ENABLED 默认关闭；命中挑战者胜出即覆盖返回文本并落库回流。
        # 任何异常回退冠军（fail-safe 双保险），绝不影响用户返回。
        returned_variant = None
        try:
            from app.services.prompt_evolution.experiment_contract import FrozenModelContract
            from app.services.prompt_evolution.experiment_privacy import PayloadVault
            from app.services.prompt_evolution.returnable_service import (
                ReturnableConfig,
                ReturnableDeps,
                returnable_reduce,
            )

            returnable_config = ReturnableConfig.from_env()
            if returnable_config.enabled:
                async def _returnable_rewrite(prompt_text, source_text, model_id):
                    return await evaluator._rewrite_text(
                        prompt_text, source_text, temperature=0.8, model_id=model_id
                    )

                async def _returnable_detect(candidate_text):
                    result = await tencent_ai_detect_service.detect_ai_content(candidate_text)
                    if not result.get("success"):
                        return None
                    return float(result.get("ai_score", 0.0))

                vault = (
                    PayloadVault(returnable_config.payload_key)
                    if returnable_config.payload_key else None
                )
                outcome = await returnable_reduce(
                    db,
                    subject_id=str(current_user.id),
                    genre=detected_genre,
                    request_id=f"req_{uuid.uuid4().hex[:16]}",
                    original_text=text,
                    champion_text=reduced_text,
                    champion_ai_score=float(new_score),
                    model_id=active_model_id,
                    contract=FrozenModelContract.freeze(
                        resolved_model_id=active_model_id or "default_route",
                        model_selection_source=selection_source,
                        model_config_version=None,
                        prompt_version_id=prompt_version_id,
                        temperature=0.8,
                    ),
                    champion_prompt_text=prompt,
                    deps=ReturnableDeps(
                        rewrite_fn=_returnable_rewrite,
                        detect_fn=_returnable_detect,
                    ),
                    config=returnable_config,
                    vault=vault,
                )
                returned_variant = outcome.returned_variant
                # 挑战者胜出：用其文本与 AI 分覆盖响应（champion 命中则保持不变）
                if outcome.returned_variant == "challenger":
                    reduced_text = outcome.returned_text
                    if outcome.challenger_ai_score is not None:
                        new_score = int(round(outcome.challenger_ai_score))
                        improvement = original_score - new_score
        except Exception as returnable_error:  # noqa: BLE001 —— 旁路红线：任何异常回退冠军
            logger.warning(f"returnable 择优旁路异常跳过: {type(returnable_error).__name__}")

        return ReduceResponse(
            success=True,
            reduced_text=reduced_text,
            original_ai_score=original_score,
            new_ai_score=new_score,
            label=new_result.get("label", "Unknown"),
            improvement=improvement,
            model_used=model_name or "默认路由",
            genre_detected=detected_genre,
            prompt_version_id=prompt_version_id,
            selection_source=selection_source,
            returned_variant=returned_variant,
        )

    except Exception as e:
        logger.error(f"降低AI痕迹失败: {str(e)}")
        return ReduceResponse(
            success=False,
            error=f"处理失败: {str(e)}"
        )


# ============================================================================
# 管理员：模型配置管理
# ============================================================================

class SetModelConfigRequest(BaseModel):
    """设置活跃模型请求"""
    model_id: Optional[str] = None  # None 表示清除手动选定，回退到自动最优


@router.get("/model-config")
async def get_model_config(
    genre: Optional[str] = None,
    current_user: User = Depends(require_admin)
):
    """
    获取当前模型配置

    返回当前活跃模型信息、管理员选定状态、自动最优模型。
    """
    service = get_multi_model_service()
    config = service.get_model_config(normalize_genre(genre))
    return {"success": True, **config}


@router.post("/model-config")
async def set_model_config(
    request: SetModelConfigRequest,
    current_user: User = Depends(require_admin)
):
    """
    管理员设置活跃模型

    传入 model_id 选定模型，传 null 清除选定并回退到自动最优。
    """
    service = get_multi_model_service()

    # 验证模型ID有效性
    if request.model_id:
        from app.services.ai_trace_competition import _MODEL_INFO_MAP
        if request.model_id not in _MODEL_INFO_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"无效的模型ID: {request.model_id}"
            )

    service.set_admin_model(request.model_id)
    config = service.get_model_config()
    return {"success": True, "message": "模型配置已更新", **config}


# ============================================================================
# 管理员：查看可用模型及其表现
# ============================================================================

@router.get("/available-models")
async def get_available_models(
    genre: Optional[str] = None,
    current_user: User = Depends(require_admin)
):
    """
    获取可参与改写评估的模型列表

    返回模型基本信息和历史表现数据（平均AI分数、降分幅度等）。
    支持按题材筛选（不同题材下淘汰状态和表现可能不同）。
    """
    service = get_multi_model_service()
    models = service.get_available_models(genre)
    return {
        "success": True,
        "models": models,
        "total": len(models),
        "genre": genre or "通用",
    }


# ============================================================================
# 管理员：多模型评测（用于提示词进化系统或手动评测）
# ============================================================================

class EvaluateModelsRequest(BaseModel):
    """多模型评测请求"""
    text: str
    intensity: Optional[str] = "medium"
    models: Optional[List[str]] = None
    original_ai_score: Optional[int] = None
    genre: Optional[str] = None


class EvaluateModelResult(BaseModel):
    """单个模型评测结果"""
    model_id: str
    model_name: str
    provider: str
    reduced_text: str
    ai_score: int
    latency_seconds: float
    improvement: int
    fidelity_similarity: float = 100.0


class EvaluateModelsResponse(BaseModel):
    """多模型评测响应"""
    success: bool
    original_ai_score: Optional[int] = None
    results: List[EvaluateModelResult] = Field(default_factory=list)
    total_models_tried: int = 0
    total_models_success: int = 0
    total_time_seconds: float = 0.0
    ranking: Optional[dict] = None
    error: Optional[str] = None


@router.post("/evaluate-models", response_model=EvaluateModelsResponse)
async def evaluate_models(
    request: EvaluateModelsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    多模型评测 - 管理员/进化系统专用

    并发调用所有模型改写同一文本，检测AI分数后按效果排序。
    结果会更新模型历史表现记录，并自动计算最优模型。
    """
    text = request.text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="请提供待处理的文本内容")

    if len(text) < 50:
        raise HTTPException(status_code=400, detail="文本过短，请提供至少50个字符")

    if len(text) > 10000:
        text = text[:10000]

    logger.info(f"管理员多模型评测启动: 文本长度={len(text)}, 模型={request.models or '全部'}")
    genre = normalize_genre(request.genre)
    coordinator = get_background_optimization_coordinator()
    lease = coordinator.try_start("manual_evaluation", genre)
    if lease is None:
        raise HTTPException(status_code=409, detail="已有后台优化任务运行中或处于冷却期")
    if not coordinator.consume_budget(1):
        lease.finish(status="budget_exhausted")
        raise HTTPException(status_code=429, detail="今日全模型评测预算已用尽")

    lease_status = "completed"
    try:
        # 获取提示词
        meta_optimizer = MetaOptimizer()
        storage = EvolutionStorage()

        selection = storage.get_prompt_selection(genre)
        optimized_prompt = selection["prompt_text"] if selection else meta_optimizer.get_initial_prompt(genre=genre)

        output_requirements = (
            "【输出要求】\n"
            "只输出改写后的文本，保持原文段落结构，不要任何解释、标题或列表。"
        )

        def ensure_output_requirements(prompt_text: str) -> str:
            if "只输出改写后的文本" in prompt_text:
                return prompt_text
            return f"{prompt_text}\n\n{output_requirements}"

        base_intensity_prompts = {
            "light": (
                "请对以下文本进行轻微润色，保持原意不变的前提下，做小幅表达优化，"
                "使其更自然、更像人类写作。\n\n【改写范围】\n"
                "1. 仅做措辞、语序、节奏、标点的轻微调整\n"
                "2. 不增删关键事实，不改变叙述视角\n"
                "3. 尽量保持原文段落结构"
            ),
            "medium": optimized_prompt,
            "strong": f"""{optimized_prompt}

【深度改写附加要求】
1. 彻底重构句式，避免常见的对称结构
2. 替换常见的模板化连接词（如"首先/其次/总之"等）
3. 增加口语化表达与个体化视角
4. 打破段落过度规整，制造更自然的阅读节奏
5. 加入适当语气词与转折停顿
6. 保持核心意思不变，但用完全不同的方式表达
改写后的文本应读起来像是一位有经验的人类作者写的"""
        }

        base_prompt = base_intensity_prompts.get(
            request.intensity, base_intensity_prompts["medium"]
        )
        prompt = ensure_output_requirements(base_prompt)

        # 调用多模型评估
        service = get_multi_model_service()
        result = await service.evaluate_across_models(
            text=text,
            prompt=prompt,
            models=request.models,
            temperature=0.8,
            original_ai_score=request.original_ai_score,
            genre=genre,
            prompt_version_id=(selection["version_id"] if selection else f"initial-{genre}"),
        )

        return EvaluateModelsResponse(
            success=result["success"],
            original_ai_score=result["original_ai_score"],
            results=[EvaluateModelResult(**r) for r in result["results"]],
            total_models_tried=result["total_models_tried"],
            total_models_success=result["total_models_success"],
            total_time_seconds=result["total_time_seconds"],
            ranking=result.get("ranking"),
        )

    except Exception as e:
        lease_status = "failed"
        logger.error(f"多模型评测失败: {str(e)}")
        return EvaluateModelsResponse(
            success=False,
            error=f"评测失败: {str(e)}"
        )
    finally:
        lease.finish(status=lease_status)


@router.get("/evaluation-metrics")
async def get_evaluation_metrics(
    genre: Optional[str] = None,
    current_user: User = Depends(require_admin),
):
    service = get_multi_model_service()
    return {
        "success": True,
        "genre": normalize_genre(genre),
        "metrics": service.config_storage.get_evaluation_metrics(normalize_genre(genre)),
    }


@router.get("/model-combinations")
async def get_model_combinations(
    genre: Optional[str] = None,
    current_user: User = Depends(require_admin),
):
    service = get_multi_model_service()
    target = normalize_genre(genre)
    if target == "通用":
        # "通用"视角合并全部题材的联合表现（数据按具体题材分库记录）
        all_records = service.config_storage.load_all_combination_performance()
        combinations = [
            {**record.__dict__, "genre": genre_key, "is_current": False}
            for genre_key, genre_records in all_records.items()
            for models in genre_records.values()
            for record in models.values()
        ]
        combinations.sort(key=lambda item: item["composite_score"])
        return {"success": True, "genre": target, "combinations": combinations}
    records = service.config_storage.load_combination_performance(target)
    prompt_selection = EvolutionStorage().get_prompt_selection(target)
    model_config = service.get_model_config(target)
    combination = (
        service.get_best_model_for_prompt_version(target, prompt_selection["version_id"])
        if prompt_selection and not model_config.get("admin_selected_model") else None
    )
    active_model_id = combination.model_id if combination else service.get_active_model_id(target)
    combinations = [
        {
            **record.__dict__,
            "genre": target,
            "is_current": bool(
                prompt_selection
                and record.prompt_version_id == prompt_selection["version_id"]
                and record.model_id == active_model_id
            ),
        }
        for models in records.values()
        for record in models.values()
    ]
    combinations.sort(key=lambda item: item["composite_score"])
    return {"success": True, "genre": target, "combinations": combinations}


@router.get("/background-status")
async def get_background_status(current_user: User = Depends(require_admin)):
    return {
        "success": True,
        **get_background_optimization_coordinator().get_status(),
    }
