"""
AI痕迹降低 API
提供文本AI痕迹检测与降低功能
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
import time

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.tencent_ai_detect import tencent_ai_detect_service
from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.storage import EvolutionStorage

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai-trace", tags=["AI Trace"])


class ReduceRequest(BaseModel):
    """降低AI浓度请求"""
    text: str
    intensity: Optional[str] = "medium"  # light, medium, strong


class ReduceResponse(BaseModel):
    """降低AI浓度响应"""
    success: bool
    reduced_text: Optional[str] = None
    original_ai_score: Optional[int] = None
    new_ai_score: Optional[int] = None
    label: Optional[str] = None
    improvement: Optional[int] = None
    error: Optional[str] = None


@router.post("/reduce", response_model=ReduceResponse)
async def reduce_ai_trace(
    request: ReduceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    降低文本的AI痕迹
    
    使用提示词进化引擎的改写能力来降低文本的AI浓度
    """
    text = request.text.strip()
    
    if not text:
        raise HTTPException(status_code=400, detail="请提供待处理的文本内容")
    
    if len(text) < 50:
        raise HTTPException(status_code=400, detail="文本过短，请提供至少50个字符")
    
    # 文本长度限制
    if len(text) > 10000:
        logger.warning(f"文本过长 ({len(text)} 字符)，截取前 10000 字符进行处理")
        text = text[:10000]
    
    logger.info(f"开始降低AI痕迹，文本长度: {len(text)} 字符, 强度: {request.intensity}")
    start_time = time.time()
    
    try:
        # 1. 先检测原始文本的AI分数
        step1_start = time.time()
        original_result = await tencent_ai_detect_service.detect_ai_content(text[:5000])
        original_score = original_result.get("ai_score", 50) if original_result.get("success") else 50
        logger.info(f"  ✅ 步骤1-原始检测完成，耗时: {time.time() - step1_start:.2f}秒, 分数: {original_score}")
        
        # 2. 使用提示词进化引擎的改写能力
        evaluator = PromptEvaluator()
        meta_optimizer = MetaOptimizer()
        storage = EvolutionStorage()

        # 获取优化后的最佳提示词（优先级：已批准 > 历史最佳 > 初始提示词）
        def get_optimized_prompt() -> str:
            # 1. 优先使用已批准的提示词
            approved = storage.get_latest_approved_prompt()
            if approved and approved.get("prompt_text"):
                logger.info(f"✨ 使用已批准的提示词 (得分: {approved.get('avg_ai_score', '?')})")
                return approved["prompt_text"]

            # 2. 其次使用历史最佳提示词
            best_prompts = storage.load_best_prompts()
            if best_prompts:
                # 选择得分最低（效果最好）的
                best = min(best_prompts, key=lambda p: p.avg_ai_score)
                if best.avg_ai_score < 80:  # 只有足够好的才使用
                    logger.info(f"✨ 使用历史最佳提示词 (得分: {best.avg_ai_score:.1f})")
                    return best.prompt_text

            # 3. 回退到初始提示词
            logger.info("📝 使用初始提示词（无优化版本可用）")
            return meta_optimizer.get_initial_prompt()

        # 根据强度选择不同的提示词
        optimized_prompt = get_optimized_prompt()

        intensity_prompts = {
            "light": "请对以下文本进行轻微润色，保持原意的同时略微调整表达方式，使其更加自然流畅。",
            "medium": optimized_prompt,  # 🆕 使用优化后的提示词
            "strong": f"""{optimized_prompt}

【深度改写附加要求】
1. 彻底重构句式，避免AI常见的对称结构
2. 替换所有常见的AI用语（如"首先、其次、总之"等）
3. 增加口语化表达和个人化视角
4. 打破段落的规整性，创造自然的阅读节奏
5. 加入适当的语气词和转折
6. 保持原文的核心意思，但用完全不同的方式表达

改写后的文本应该读起来像是一位有经验的人类作者写的。"""
        }

        prompt = intensity_prompts.get(request.intensity, intensity_prompts["medium"])
        
        # 调用改写
        step2_start = time.time()
        reduced_text = await evaluator._rewrite_text(prompt, text, temperature=0.8)
        logger.info(f"  ✅ 步骤2-LLM改写完成，耗时: {time.time() - step2_start:.2f}秒, 输出长度: {len(reduced_text)}字符")
        
        # 3. 检测改写后的AI分数
        step3_start = time.time()
        new_result = await tencent_ai_detect_service.detect_ai_content(reduced_text[:5000])
        new_score = new_result.get("ai_score", original_score) if new_result.get("success") else original_score
        logger.info(f"  ✅ 步骤3-改写后检测完成，耗时: {time.time() - step3_start:.2f}秒, 新分数: {new_score}")
        
        improvement = original_score - new_score
        total_time = time.time() - start_time
        
        logger.info(f"AI痕迹降低完成: {original_score} -> {new_score} (降低 {improvement} 分)，总耗时: {total_time:.2f}秒")
        
        response = ReduceResponse(
            success=True,
            reduced_text=reduced_text,
            original_ai_score=original_score,
            new_ai_score=new_score,
            label=new_result.get("label", "Unknown"),
            improvement=improvement
        )
        
        logger.info(f"✏️ 准备返回响应，数据大小: {len(reduced_text)}字符")
        return response
        
    except Exception as e:
        logger.error(f"降低AI痕迹失败: {str(e)}")
        return ReduceResponse(
            success=False,
            error=f"处理失败: {str(e)}"
        )

