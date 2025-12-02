"""
提示词进化系统 - 评估器

封装AI检测调用，评估改写效果
"""
import asyncio
import logging
from typing import List, Tuple, Optional, Dict, Any

from app.services.tencent_ai_detect import tencent_ai_detect_service
from app.services.llm_client import get_llm_client
from app.services.model_optimizer import TaskType

from .models import EvaluationResult, AITraceDetail
from .test_samples import TestSample
from .novel_rules import (
    preprocess_text, postprocess_text, ALL_FORBIDDEN_WORDS,
    calculate_text_metrics, compare_metrics, TextMetrics,
    calculate_multi_dimension_score, MultiDimensionScore
)

logger = logging.getLogger(__name__)


class PromptEvaluator:
    """提示词评估器"""
    
    def __init__(self):
        self.llm_client = get_llm_client()
        self.ai_detector = tencent_ai_detect_service
    
    async def evaluate_prompt(
        self,
        prompt: str,
        samples: List[TestSample],
        temperature: float = 0.8
    ) -> Tuple[float, List[EvaluationResult]]:
        """
        评估提示词效果
        
        Args:
            prompt: 待评估的改写提示词
            samples: 测试样本列表
            temperature: LLM温度参数
            
        Returns:
            (平均AI得分, 评估结果列表)
        """
        results: List[EvaluationResult] = []
        total_score = 0
        success_count = 0
        
        for sample in samples:
            print(f"📝 [评估器] 评估样本: {sample.sample_id} ({sample.genre})")
            logger.info(f"📝 评估样本: {sample.sample_id} ({sample.genre})")

            try:
                # 1. 使用提示词改写文本
                print(f"   ⏳ 正在改写文本...")
                rewritten = await self._rewrite_text(prompt, sample.text, temperature)
                print(f"   ✅ 改写完成，长度: {len(rewritten)}")
                
                if not rewritten or len(rewritten.strip()) < 50:
                    results.append(EvaluationResult(
                        sample_id=sample.sample_id,
                        original_text=sample.text,
                        rewritten_text="",
                        original_ai_score=None,
                        rewritten_ai_score=None,
                        score_reduction=0,
                        success=False,
                        error="改写结果过短或为空"
                    ))
                    continue
                
                # 2. 检测原始文本的AI率
                print(f"   ⏳ 检测原始文本AI率...")
                original_result = await self.ai_detector.detect_ai_content(sample.text[:5000])
                original_trace_detail = None
                if original_result.get("success"):
                    original_score = original_result.get("ai_score", 100)
                    # 提取AI痕迹详情
                    trace_data = original_result.get("ai_trace_details", {})
                    if trace_data:
                        original_trace_detail = AITraceDetail(
                            hit_keywords=trace_data.get("hit_keywords", []),
                            hit_positions=trace_data.get("hit_positions", []),
                            detection_method=trace_data.get("detection_method", ""),
                            label_scores=trace_data.get("label_scores", {}),
                            problematic_segments=trace_data.get("problematic_segments", [])
                        )
                else:
                    original_score = 100
                    print(f"   ⚠️ 原始文本检测失败: {original_result.get('error', '未知错误')}")
                print(f"   📊 原始AI得分: {original_score}")

                # 3. 检测改写后文本的AI率
                print(f"   ⏳ 检测改写后文本AI率...")
                rewritten_result = await self.ai_detector.detect_ai_content(rewritten[:5000])
                rewritten_trace_detail = None
                if rewritten_result.get("success"):
                    rewritten_score = rewritten_result.get("ai_score", 100)
                    # 提取AI痕迹详情
                    trace_data = rewritten_result.get("ai_trace_details", {})
                    if trace_data:
                        rewritten_trace_detail = AITraceDetail(
                            hit_keywords=trace_data.get("hit_keywords", []),
                            hit_positions=trace_data.get("hit_positions", []),
                            detection_method=trace_data.get("detection_method", ""),
                            label_scores=trace_data.get("label_scores", {}),
                            problematic_segments=trace_data.get("problematic_segments", [])
                        )
                        # 输出发现的问题
                        if trace_data.get("hit_keywords"):
                            print(f"   🔍 发现AI痕迹关键词: {trace_data['hit_keywords']}")
                        if trace_data.get("detection_method"):
                            print(f"   🔍 检测方法: {trace_data['detection_method']}")
                else:
                    rewritten_score = 100
                    print(f"   ⚠️ 改写文本检测失败: {rewritten_result.get('error', '未知错误')}")
                print(f"   📊 改写后AI得分: {rewritten_score}")

                # 4. 计算得分下降
                score_reduction = original_score - rewritten_score

                # 5. 计算量化指标
                original_metrics = calculate_text_metrics(sample.text)
                rewritten_metrics = calculate_text_metrics(rewritten)
                metrics_comparison = compare_metrics(original_metrics, rewritten_metrics)

                print(f"   📈 原文指标: {original_metrics.to_summary()}")
                print(f"   📈 改写指标: {rewritten_metrics.to_summary()}")
                print(f"   📈 指标变化: {metrics_comparison}")

                # 🆕 6. 计算多维评分（含可读性）
                # 🔧 传入AI检测分数，应用AI率软性约束
                original_multi_score = calculate_multi_dimension_score(
                    sample.text, original_metrics, ai_score=original_score
                )
                rewritten_multi_score = calculate_multi_dimension_score(
                    rewritten, rewritten_metrics, ai_score=rewritten_score
                )

                print(f"   🎯 原文多维评分: {original_multi_score.to_summary()}", flush=True)
                print(f"   🎯 改写多维评分: {rewritten_multi_score.to_summary()}", flush=True)

                # 🔧 显示AI率调整信息
                if "ai_rate_adjustment" in rewritten_multi_score.details:
                    print(f"   📊 AI率调整: {rewritten_multi_score.details['ai_rate_adjustment']}", flush=True)

                # 🆕 显示可读性警告
                if rewritten_multi_score.readability_warnings:
                    print(f"   ⚠️ 可读性警告:", flush=True)
                    for warning in rewritten_multi_score.readability_warnings[:3]:  # 最多显示3条
                        print(f"      - {warning}", flush=True)

                # 🆕 可读性严重下降时给出强警告
                if rewritten_multi_score.readability_score < 60:
                    print(f"   🚨 可读性严重下降! (得分: {rewritten_multi_score.readability_score:.0f})", flush=True)
                    print(f"      建议: 当前改写可能过度优化，影响阅读体验", flush=True)

                results.append(EvaluationResult(
                    sample_id=sample.sample_id,
                    original_text=sample.text,
                    rewritten_text=rewritten,
                    original_ai_score=original_score,
                    rewritten_ai_score=rewritten_score,
                    score_reduction=score_reduction,
                    success=True,
                    original_trace_detail=original_trace_detail,
                    rewritten_trace_detail=rewritten_trace_detail,
                    # 🆕 量化指标
                    original_metrics={
                        "period_ratio": original_metrics.period_ratio,
                        "emotion_punct_ratio": original_metrics.emotion_punct_ratio,
                        "avg_sentence_length": original_metrics.avg_sentence_length,
                        "sentence_length_variance": original_metrics.sentence_length_variance,
                        "short_sentence_ratio": original_metrics.short_sentence_ratio,
                        "forbidden_word_count": original_metrics.forbidden_word_count,
                    },
                    rewritten_metrics={
                        "period_ratio": rewritten_metrics.period_ratio,
                        "emotion_punct_ratio": rewritten_metrics.emotion_punct_ratio,
                        "avg_sentence_length": rewritten_metrics.avg_sentence_length,
                        "sentence_length_variance": rewritten_metrics.sentence_length_variance,
                        "short_sentence_ratio": rewritten_metrics.short_sentence_ratio,
                        "forbidden_word_count": rewritten_metrics.forbidden_word_count,
                    },
                    metrics_comparison=metrics_comparison,
                    # 🆕 多维评分
                    original_multi_score=original_multi_score.to_dict(),
                    rewritten_multi_score=rewritten_multi_score.to_dict()
                ))
                
                total_score += rewritten_score
                success_count += 1
                
                logger.info(
                    f"  ✅ 原始: {original_score} → 改写后: {rewritten_score} "
                    f"(下降 {score_reduction})"
                )
                
                # 避免API限流
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"  ❌ 评估失败: {e}")
                results.append(EvaluationResult(
                    sample_id=sample.sample_id,
                    original_text=sample.text,
                    rewritten_text="",
                    original_ai_score=None,
                    rewritten_ai_score=None,
                    score_reduction=0,
                    success=False,
                    error=str(e)
                ))
        
        # 计算平均得分
        avg_score = total_score / success_count if success_count > 0 else 100.0
        
        logger.info(f"📊 评估完成: 平均AI得分 = {avg_score:.1f}")
        
        return avg_score, results
    
    async def _rewrite_text(self, prompt: str, original_text: str, temperature: float) -> str:
        """使用提示词改写文本（三层架构：预处理 → LLM改写 → 后处理）"""

        # ========== 第1层：规则预处理 ==========
        preprocessed_text, preprocess_logs = preprocess_text(original_text)
        if preprocess_logs:
            logger.debug(f"📝 预处理: {', '.join(preprocess_logs)}")

        # ========== 第2层：LLM改写 ==========
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"请改写以下文本，降低其AI痕迹：\n\n{preprocessed_text}"}
        ]

        # 强制使用 deepseek-chat 模型（更快更适合文风改写，不需要推理）
        llm_result = await self.llm_client.chat(
            messages=messages,
            model="deepseek-chat",  # 直接指定模型，绕过策略配置
            temperature=temperature,
            use_cache=False  # 禁用缓存以获得多样性
        )

        # ========== 第3层：规则后处理 ==========
        final_result, postprocess_logs = postprocess_text(llm_result.strip())
        if postprocess_logs:
            logger.debug(f"📝 后处理: {', '.join(postprocess_logs)}")

        # 检查禁用词残留
        remaining_forbidden = [w for w in ALL_FORBIDDEN_WORDS if w in final_result]
        if remaining_forbidden:
            logger.warning(f"⚠️ 残留禁用词: {remaining_forbidden[:5]}...")

        return final_result
    
    async def quick_detect(self, text: str) -> Dict[str, Any]:
        """快速检测单段文本的AI率"""
        result = await self.ai_detector.detect_ai_content(text[:5000])
        return {
            "success": result.get("success", False),
            "ai_score": result.get("ai_score"),
            "label": result.get("label"),
            "error": result.get("error")
        }

