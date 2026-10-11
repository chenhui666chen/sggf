"""
提示词进化系统 - 评估器

封装AI检测调用，评估改写效果
"""
import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from app.services.zhuque_ai_detect import zhuque_ai_detect_service
from core.unified_llm_client import get_llm_client
from core.model_resolution import TaskType, build_thinking_disabled_extra_body

from .models import EvaluationResult, AITraceDetail
from .test_samples import TestSample
from .semantic_judge import SemanticJudge, calculate_hybrid_score
from .novel_rules import (
    preprocess_text, postprocess_text, ALL_FORBIDDEN_WORDS,
    calculate_text_metrics, compare_metrics, TextMetrics,
    calculate_multi_dimension_score, MultiDimensionScore,
    _calculate_fidelity_score,  # 🆕 新增：保真度计算函数
    locate_high_risk_segments, build_targeted_rewrite_hint,  # 🔧 统计预检→定点改写
    build_detector_segment_hint,  # 🔧 真实检测段落标注→定点改写（替代盲猜）
    FACT_BOTTOM_LINE_HINT,  # 🔧 常驻事实底线（无定点命中时的兜底约束）
)

logger = logging.getLogger(__name__)


class _CachedDetectorProxy:
    """代理检测器：detect_ai_content 走评估器的样本级缓存

    供样本基线检测使用，使基线检测结果可被后续 evaluate_prompt 复用。
    """

    def __init__(self, evaluator: "PromptEvaluator"):
        self._evaluator = evaluator

    async def detect_ai_content(self, text: str) -> Dict[str, Any]:
        return await self._evaluator._detect_original_cached(text)


class PromptEvaluator:
    """提示词评估器"""

    # 样本级评估最大并发数：改写/检测/评审为 IO 密集调用，8 路并发可压缩评估段耗时
    EVALUATION_CONCURRENCY = 8
    # 🔧 篇幅守门参数：改写长度不得低于原文 MIN_REWRITE_RATIO；
    # 原文≥ GATE_ABSOLUTE_ORIGINAL_THRESHOLD 字时另受 MIN_REWRITTEN_LENGTH 绝对下限约束
    #
    # ⚠️ MIN_REWRITTEN_LENGTH 由 600 上调至 1500（2026-10-08 真实网关实测）：
    #    同一篇人工改写文本按长度截断扫描得 100字→100分、300字→100分、600字→100分、
    #    1000字→53分、1600字→33分。即 600 字以下检测分完全失真（恒判满分 AI），
    #    落在失真区的改写会拿到虚假的「零降分」甚至虚假满分，污染进化方向。
    #    注：此处原注释称「朱雀约300字以下返回0分」与实测相反（实测返回100分），已订正。
    MIN_REWRITE_RATIO = 0.5
    MIN_REWRITTEN_LENGTH = 1500
    GATE_ABSOLUTE_ORIGINAL_THRESHOLD = 1200
    # 🔧 去锚定重写开关（2026-10-08 实测）：改用「原文→事实要点→重新生成」两阶段范式，
    # 可把「被判确定AI」的段落占比从 100% 降到约 26%（常规改写只能降到 50% 左右）。
    # 代价：单次改写的 LLM 调用由 1 次增至 2-3 次，成本与延迟翻倍。
    # 故默认关闭，由 AI_TRACE_DEANCHOR_ENABLED=true 显式启用，失败自动回退常规改写。
    DEANCHOR_ENABLED = os.getenv("AI_TRACE_DEANCHOR_ENABLED", "false").strip().lower() == "true"
    # 🔧 改写空响应重试上限：改写模型偶发返回空串（历史题材实测 3/4 样本），
    # 不重试会导致样本硬失败、变体/基线被批量取消资格
    REWRITE_MAX_ATTEMPTS = 3
    # 🔧 高方差模型高分重试：step 系历史 0 分率 22-43%（赌徒分布，单次抽样
    # 期望分 ~54-70；0 分记录 30/32 保真合格，是真实大幅重写非崩坏）。
    # 检测分仍高时再改写一次取低分，使命中概率接近翻倍（40%→64%）。
    # mimo 系存在 64/98 波动（无 step 的稳定 0 分能力），重试可将 98 拉低，
    # 收益虽低于 step 但成本可控，一并纳入（2026-08-23 实测扩展）
    HIGH_SCORE_RETRY_THRESHOLD = 70
    HIGH_SCORE_RETRY_MAX = 0  # TMS 移除后停用（详见 _eval_one_sample 注释）
    HIGH_SCORE_RETRY_MODEL_PREFIXES = ("step", "mimo")
    # 🔧 StepFun 阶梯限速：API 并发上限 5（429 实测），评估并发 8 全为
    # step 时（如武侠题材进化）会触发限流；模型级信号量压到 4 留 buffer
    MODEL_MAX_CONCURRENCY = {"step": 4}
    # 🔧 深区定点改写阈值：基线≥此分才附定点提示；低分样本无差别全文
    # 改写已有效，附提示反而限制发挥（基准实验：深区对全文改写免疫）
    DEEP_ZONE_HINT_THRESHOLD = 90
    # 🔧 真实检测段落标注定点改写（2026-10-08）：朱雀逐段返回 label（0人工/1确定AI/2疑似）
    # 与段原文，这是检测器给出的**真值**；而 locate_high_risk_segments 只是正则猜
    # 「这段可能像 AI」，检测器认不认并不知道。
    # 启用后：有确定AI段落时优先用真值指令，无则回退正则预检。
    # 默认关闭——实验13 已证明往提示词加指令有伤害主指标的风险，
    # 需先由 A/B 对照实验（见 .workbuddy/memory/2026-10-08.md）确认收益再开。
    SEGMENT_HINT_ENABLED = os.getenv("AI_TRACE_SEGMENT_HINT_ENABLED", "false").strip().lower() == "true"
    # 🔧 常驻事实底线（2026-10-08）：无任何定点命中时，仍下发 FACT_BOTTOM_LINE_HINT。
    # 依据实验16：无指令组质量合格率 25%（事实一致性均值 85），有指令组 75%（均值 90）。
    # 干净样本不应因"没命中"就裸奔——事实约束是普适要求，不是定点专属。
    FACT_HINT_ENABLED = os.getenv("AI_TRACE_FACT_HINT_ENABLED", "false").strip().lower() == "true"

    def __init__(self):
        self.llm_client = get_llm_client()
        self.ai_detector = zhuque_ai_detect_service
        self.semantic_judge = SemanticJudge(self.llm_client)
        # 🆕 样本原文检测缓存：同一进化运行内，每个样本原文只检测一次
        # key = 文本哈希, value = 检测结果 dict
        self._original_detect_cache: Dict[str, Dict[str, Any]] = {}
        # 🆕 缓存代理检测器：基线检测与评估共享同一缓存
        self.cached_detector = _CachedDetectorProxy(self)
        # 🔧 样本级并发限流：惰性创建以绑定首次使用时的事件循环
        self._sample_semaphore: Optional[asyncio.Semaphore] = None
        # 🔧 模型级并发限流（StepFun 阶梯限速等）
        self._model_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._original_cache_lock: Optional[asyncio.Lock] = None
        # 🔧 改写全文临时工作区：由引擎在本批次启动时注入，评估批次落盘
        # 完整原文/改写/评审记录供过程中取证；批次结束后由引擎整目录删除
        self.workspace_dir: Optional[Path] = None

    async def _detect_original_cached(self, text: str) -> Dict[str, Any]:
        """检测原始文本AI率（带样本级缓存，避免重复付费检测）"""
        prepared_text = zhuque_ai_detect_service.prepare_text(text)
        cache_key = hashlib.md5(prepared_text.encode("utf-8")).hexdigest()
        cached = self._original_detect_cache.get(cache_key)
        if cached is not None:
            logger.debug("   ♻️ 命中原文检测缓存，跳过重复检测")
            return cached
        # 🔧 并发评估下防止同一原文被重复检测（双重检查锁定）
        if self._original_cache_lock is None:
            self._original_cache_lock = asyncio.Lock()
        async with self._original_cache_lock:
            cached = self._original_detect_cache.get(cache_key)
            if cached is not None:
                return cached
            result = await self.ai_detector.detect_ai_content(prepared_text)
            # 仅缓存成功结果，失败时下次仍可重试
            if result.get("success"):
                self._original_detect_cache[cache_key] = result
        return result

    def get_cached_original_score(self, text: str) -> Optional[int]:
        """查询样本原文的缓存AI分数（无缓存时返回None）"""
        prepared_text = zhuque_ai_detect_service.prepare_text(text)
        cache_key = hashlib.md5(prepared_text.encode("utf-8")).hexdigest()
        cached = self._original_detect_cache.get(cache_key)
        if cached is not None:
            return cached.get("ai_score")
        return None
    
    async def evaluate_prompt(
        self,
        prompt: str,
        samples: List[TestSample],
        temperature: float = 0.8,
        model_id: Optional[str] = None
    ) -> Tuple[float, List[EvaluationResult]]:
        """
        评估提示词效果
        
        Args:
            prompt: 待评估的改写提示词
            samples: 测试样本列表
            temperature: LLM温度参数
            model_id: 指定改写执行模型（None时使用默认路由）
            
        Returns:
            (平均AI得分, 评估结果列表)
        """
        
        results: List[EvaluationResult] = await self._evaluate_samples_concurrently(
            prompt, samples, temperature, model_id
        )

        # 计算平均得分
        total_score = sum(
            r.rewritten_ai_score for r in results
            if r.success and r.rewritten_ai_score is not None
        )
        success_count = sum(1 for r in results if r.success)

        avg_score = total_score / success_count if success_count > 0 else 100.0

        logger.info(f"📊 评估完成: 平均AI得分 = {avg_score:.1f}")

        # 🔧 工作区落盘：完整记录本评估批次（含失格候选），供过程中取证分析
        self._dump_workspace(prompt, temperature, model_id, results)

        return avg_score, results

    def _dump_workspace(
        self,
        prompt: str,
        temperature: float,
        model_id: Optional[str],
        results: List[EvaluationResult],
    ) -> None:
        """将本评估批次的完整记录落盘到临时工作区（未启用时跳过）。

        历史存档对改写文本统一截断100字且失格候选不落盘，导致硬失败无法
        取证；此处保存全文，批次结束后由引擎整目录删除，不积留文件。
        落盘失败不影响评估主流程。
        """
        if self.workspace_dir is None:
            return
        try:
            record = {
                "dumped_at": datetime.now().isoformat(),
                "prompt": prompt,
                "temperature": temperature,
                "model_id": model_id,
                "results": [
                    {
                        "sample_id": r.sample_id,
                        "original_text": r.original_text,
                        "rewritten_text": r.rewritten_text,
                        "original_text_length": len(r.original_text),
                        "rewritten_text_length": len(r.rewritten_text),
                        "original_ai_score": r.original_ai_score,
                        "rewritten_ai_score": r.rewritten_ai_score,
                        "score_reduction": r.score_reduction,
                        "success": r.success,
                        "error": r.error,
                        "llm_review": r.llm_review,
                    }
                    for r in results
                ],
            }
            filename = f"eval_{datetime.now().strftime('%H%M%S%f')}_{uuid.uuid4().hex[:6]}.json"
            with open(self.workspace_dir / filename, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=1)
        except Exception as dump_err:
            logger.warning(f"⚠️ 工作区落盘失败（不影响评估）: {dump_err}")

    async def _evaluate_single_sample(
        self,
        prompt: str,
        sample: TestSample,
        temperature: float,
        model_id: Optional[str] = None,
    ) -> EvaluationResult:
        """评估单个样本：改写 → 朱雀检测 → 语义评审 → 多维评分。

        并发执行时由 _evaluate_samples_concurrently 的信号量限流。
        """
        logger.debug(f"📝 [评估器] 评估样本: {sample.sample_id} ({sample.genre})")
        logger.info(f"📝 评估样本: {sample.sample_id} ({sample.genre})")
        try:
            # 1. 先检测原始文本（样本级缓存：首次进入本次进化时检测一次）
            logger.debug(f"   ⏳ 检测原始文本AI率...")
            policy_version = zhuque_ai_detect_service.detection_policy_version
            original_result = sample.get_ai_detection(policy_version)
            if original_result is not None:
                prepared_text = zhuque_ai_detect_service.prepare_text(sample.text)
                cache_key = hashlib.md5(prepared_text.encode("utf-8")).hexdigest()
                self._original_detect_cache.setdefault(cache_key, original_result)
            else:
                original_result = await self._detect_original_cached(sample.text)
                if original_result.get("success"):
                    sample.store_ai_detection(original_result, policy_version)
            if original_result.get("success") and original_result.get("ai_score") == 0:
                logger.warning("样本 %s 原始 AI 率为 0，已排除", sample.sample_id)
                return EvaluationResult(
                    sample_id=sample.sample_id,
                    original_text=sample.text,
                    rewritten_text="",
                    original_ai_score=0,
                    rewritten_ai_score=None,
                    score_reduction=0,
                    success=False,
                    error="原始样本AI率为0，已排除"
                )

            # 🔧 统计预检：深区（基线≥阈值）先定位高风险结构句式再定点改写，
            # 比无差别全文改写有效（humanize_mba 工程闭环实证）；低分样本
            # 零污染，继续走普通全文改写链路
            # 🔧 定点指令优先级：真实检测段落标注（真值）> 正则统计预检（猜测）
            # 真值可用时不再叠加正则预检——两者同时下发会显著拉长指令、
            # 挤占事实约束的注意力预算（实验13 教训）
            targeted_hint = ""
            original_findings: List[Dict[str, Any]] = []
            hint_source = "无"
            if self.SEGMENT_HINT_ENABLED and original_result.get("success"):
                targeted_hint = build_detector_segment_hint(
                    original_result.get("segment_labels") or []
                )
                if targeted_hint:
                    hint_source = "真实段落标注"
            if not targeted_hint and original_result.get("success") and (
                original_result.get("ai_score") or 0
            ) >= self.DEEP_ZONE_HINT_THRESHOLD:
                original_findings = locate_high_risk_segments(sample.text)
                targeted_hint = build_targeted_rewrite_hint(original_findings)
                if targeted_hint:
                    hint_source = "正则预检"
            # 🔧 兜底：两类定点指令都未命中时下发常驻事实底线。
            # 定点指令自身已含事实条款，故不叠加，避免指令过长。
            if not targeted_hint and self.FACT_HINT_ENABLED:
                targeted_hint = FACT_BOTTOM_LINE_HINT
                hint_source = "常驻事实底线"
            if targeted_hint:
                logger.info(f"   🎯 定点指令来源: {hint_source}")

            # 2. 使用提示词改写文本
            logger.debug(f"   ⏳ 正在改写文本...")
            rewritten = await self._rewrite_text(
                prompt, sample.text, temperature,
                model_id=model_id, targeted_hint=targeted_hint,
            )
            logger.debug(f"   ✅ 改写完成，长度: {len(rewritten)}")

            if not rewritten or len(rewritten.strip()) < 50:
                return EvaluationResult(
                    sample_id=sample.sample_id,
                    original_text=sample.text,
                    rewritten_text="",
                    original_ai_score=None,
                    rewritten_ai_score=None,
                    score_reduction=0,
                    success=False,
                    error="改写结果过短或为空"
                )

            # 🔧 篇幅守门：改写不得低于原文 MIN_REWRITE_RATIO；长样本另设绝对下限，
            # 防止大幅缩短落入检测器盲区（朱雀约300字以下返回0分）产生虚假满分降分
            if len(sample.text) >= self.GATE_ABSOLUTE_ORIGINAL_THRESHOLD:
                min_rewrite_len = max(
                    self.MIN_REWRITTEN_LENGTH,
                    int(len(sample.text) * self.MIN_REWRITE_RATIO),
                )
            else:
                min_rewrite_len = int(len(sample.text) * self.MIN_REWRITE_RATIO)
            if len(rewritten.strip()) < min_rewrite_len:
                logger.warning(
                    f"   ⚠️ 篇幅守门拦截: 改写{len(rewritten.strip())}字 < 下限{min_rewrite_len}字"
                    f"（原文{len(sample.text)}字），疑似内容丢失"
                )
                return EvaluationResult(
                    sample_id=sample.sample_id,
                    original_text=sample.text,
                    rewritten_text=rewritten,
                    original_ai_score=None,
                    rewritten_ai_score=None,
                    score_reduction=0,
                    success=False,
                    error=(
                        f"改写篇幅严重偏离原文（{len(rewritten.strip())}/{len(sample.text)}字），"
                        "疑似信息丢失"
                    )
                )

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
                logger.debug(f"   ⚠️ 原始文本检测失败: {original_result.get('error', '未知错误')}")
            logger.debug(f"   📊 原始AI得分: {original_score}")

            # 3. 检测改写后文本的AI率
            logger.debug(f"   ⏳ 检测改写后文本AI率...")
            rewritten_result = await self.ai_detector.detect_ai_content(rewritten)
            rewritten_trace_detail = None
            # 🔧 记录段落三分类占比：ai_score 在 LLM 改写区间恒为 100、无分辨力，
            # 真实进步体现在「确定AI」占比下降、「疑似AI」占比上升
            rewritten_ai_ratio = rewritten_result.get("ai_ratio")
            rewritten_suspect_ratio = rewritten_result.get("suspect_ratio")
            rewritten_human_ratio = rewritten_result.get("human_ratio")
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
                        logger.debug(f"   🔍 发现AI痕迹关键词: {trace_data['hit_keywords']}")
                    if trace_data.get("detection_method"):
                        logger.debug(f"   🔍 检测方法: {trace_data['detection_method']}")
            else:
                rewritten_score = 100
                logger.debug(f"   ⚠️ 改写文本检测失败: {rewritten_result.get('error', '未知错误')}")
            logger.debug(f"   📊 改写后AI得分: {rewritten_score}")

            # 🔧 高方差模型高分重试（TMS 移除后停用）：
            # TMS 为格式触发的伪检测器（2026-08-27 格式复验：对段落空格/开头空行敏感，
            # 格式干净后真人与 AI 均得 0），"检测分高→重改取低分"无意义。
            # HIGH_SCORE_RETRY_MAX 已置 0，保留代码结构备后续接入朱雀等正向
            # 检测器时重新启用。
            if (
                model_id
                and model_id.startswith(self.HIGH_SCORE_RETRY_MODEL_PREFIXES)
                and self.HIGH_SCORE_RETRY_MAX > 0
                and rewritten_score > self.HIGH_SCORE_RETRY_THRESHOLD
            ):
                for retry_no in range(1, self.HIGH_SCORE_RETRY_MAX + 1):
                    logger.info(
                        "   🎲 高方差模型高分重试（第%d次）: 当前AI分 %d > %d",
                        retry_no, rewritten_score, self.HIGH_SCORE_RETRY_THRESHOLD,
                    )
                    alt_text = await self._rewrite_text(
                        prompt, sample.text, temperature,
                        model_id=model_id, targeted_hint=targeted_hint,
                    )
                    if not alt_text or len(alt_text.strip()) < 50:
                        break
                    if len(alt_text.strip()) < min_rewrite_len:
                        logger.debug("   ⏭️ 重试产物未过篇幅守门，放弃")
                        break
                    alt_result = await self.ai_detector.detect_ai_content(alt_text)
                    if not alt_result.get("success"):
                        break
                    alt_score = alt_result.get("ai_score", 100)
                    logger.debug(f"   🎲 重试产物AI分: {alt_score}（原 {rewritten_score}）")
                    if alt_score < rewritten_score:
                        rewritten = alt_text
                        rewritten_result = alt_result
                        rewritten_score = alt_score
                    if rewritten_score <= self.HIGH_SCORE_RETRY_THRESHOLD:
                        break

            # 4. 计算得分下降
            score_reduction = original_score - rewritten_score

            # 5. 计算量化指标
            original_metrics = calculate_text_metrics(sample.text)
            rewritten_metrics = calculate_text_metrics(rewritten)
            metrics_comparison = compare_metrics(original_metrics, rewritten_metrics)

            logger.debug(f"   📈 原文指标: {original_metrics.to_summary()}")
            logger.debug(f"   📈 改写指标: {rewritten_metrics.to_summary()}")
            logger.debug(f"   📈 指标变化: {metrics_comparison}")

            # 🆕 6. 计算多维评分（含可读性 + 保真度）
            # 🔧 传入AI检测分数，应用AI率软性约束
            original_multi_score = calculate_multi_dimension_score(
                sample.text, original_metrics, ai_score=original_score
            )
            # 🆕 改写后评分：需要计算保真度（与原文的相似度）
            rewritten_multi_score = calculate_multi_dimension_score(
                rewritten, rewritten_metrics, ai_score=rewritten_score
            )
            # 🆕 计算保真度得分（越低越好，表示改动越小）
            # 字符级相似度：对「句式/用词/语序变化」敏感，会误伤有效的重构式改写
            char_fidelity = _calculate_fidelity_score(sample.text, rewritten)
            rewritten_multi_score.fidelity_score = char_fidelity
            rewritten_multi_score.details["fidelity"] = f"相似度{100-char_fidelity:.0f}%"

            llm_review = await self.semantic_judge.evaluate(
                sample.text, rewritten, sample.genre
            )
            rewritten_multi_score.overall_score = calculate_hybrid_score(
                rewritten_score, rewritten_multi_score.overall_score, llm_review
            )

            # 🔧 保真口径以「语义保真」为准（2026-10-08 实测 + 口径确认）：
            # 只要传递相同信息与情感即算保真，不要求句子顺序与用词一致。
            # 字符级相似度会惩罚彻底重构句式的有效改写——实测「强制逐句重写」
            # 字符保真仅 63.7（跌破项目 70 门槛会被判不合格），语义保真却达 98。
            # 故评审可用时一律以语义保真覆盖，字符级仅保留在 details 供诊断。
            if llm_review.get("available"):
                sem_fid = float(llm_review["semantic_fidelity"]["score"])
                rewritten_multi_score.fidelity_score = 100.0 - sem_fid
                rewritten_multi_score.details["fidelity"] = (
                    f"语义保真{sem_fid:.0f}（字符相似度{100-char_fidelity:.0f}%）"
                )

            logger.debug(f"   🎯 原文多维评分: {original_multi_score.to_summary()}", flush=True)
            logger.debug(f"   🎯 改写多维评分: {rewritten_multi_score.to_summary()}", flush=True)

            # 🔧 显示AI率调整信息
            if "ai_rate_adjustment" in rewritten_multi_score.details:
                logger.debug(f"   📊 AI率调整: {rewritten_multi_score.details['ai_rate_adjustment']}", flush=True)

            # 🆕 显示可读性警告
            if rewritten_multi_score.readability_warnings:
                logger.debug(f"   ⚠️ 可读性警告:", flush=True)
                for warning in rewritten_multi_score.readability_warnings[:3]:  # 最多显示3条
                    logger.debug(f"      - {warning}", flush=True)

            # 🆕 可读性严重下降时给出强警告
            if rewritten_multi_score.readability_score < 60:
                logger.debug(f"   🚨 可读性严重下降! (得分: {rewritten_multi_score.readability_score:.0f})", flush=True)
                logger.debug(f"      建议: 当前改写可能过度优化，影响阅读体验", flush=True)

            evaluation_success = not llm_review.get("hard_fail", False)
            evaluation_error = None
            if not evaluation_success:
                evaluation_error = "；".join(llm_review.get("hard_fail_reasons", []))

            result = EvaluationResult(
                sample_id=sample.sample_id,
                original_text=sample.text,
                rewritten_text=rewritten,
                original_ai_score=original_score,
                rewritten_ai_score=rewritten_score,
                score_reduction=score_reduction,
                success=evaluation_success,
                error=evaluation_error,
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
                    # 🔧 复测闭环：原文/改写命中数双侧落盘，供定点消除效果对比
                    "high_risk_hits": len(original_findings),
                },
                rewritten_metrics={
                    "period_ratio": rewritten_metrics.period_ratio,
                    "emotion_punct_ratio": rewritten_metrics.emotion_punct_ratio,
                    "avg_sentence_length": rewritten_metrics.avg_sentence_length,
                    "sentence_length_variance": rewritten_metrics.sentence_length_variance,
                    "short_sentence_ratio": rewritten_metrics.short_sentence_ratio,
                    "forbidden_word_count": rewritten_metrics.forbidden_word_count,
                    "high_risk_hits": len(locate_high_risk_segments(rewritten)),
                },
                metrics_comparison=metrics_comparison,
                # 🆕 多维评分
                original_multi_score=original_multi_score.to_dict(),
                rewritten_multi_score=rewritten_multi_score.to_dict(),
                llm_review=llm_review,
                rewritten_ai_ratio=rewritten_ai_ratio,
                rewritten_suspect_ratio=rewritten_suspect_ratio,
                rewritten_human_ratio=rewritten_human_ratio,
            )


            logger.info(
                f"  ✅ 原始: {original_score} → 改写后: {rewritten_score} "
                f"(下降 {score_reduction})"
            )

            return result

        except Exception as e:
            logger.error(f"  ❌ 评估失败: {e}")
            return EvaluationResult(
                sample_id=sample.sample_id,
                original_text=sample.text,
                rewritten_text="",
                original_ai_score=None,
                rewritten_ai_score=None,
                score_reduction=0,
                success=False,
                error=str(e)
            )


    async def _evaluate_samples_concurrently(
        self,
        prompt: str,
        samples: List[TestSample],
        temperature: float,
        model_id: Optional[str] = None,
    ) -> List[EvaluationResult]:
        """并发评估多个样本（信号量限流），结果顺序与输入样本一致。"""
        if self._sample_semaphore is None:
            self._sample_semaphore = asyncio.Semaphore(self.EVALUATION_CONCURRENCY)

        # 🔧 模型级并发限制：StepFun 阶梯限速并发上限 5，全 step 评估
        # （武侠题材进化等场景）需压到 4 防限流
        model_sem = None
        if model_id:
            for prefix, limit in self.MODEL_MAX_CONCURRENCY.items():
                if model_id.startswith(prefix):
                    if self._model_semaphores.get(prefix) is None:
                        self._model_semaphores[prefix] = asyncio.Semaphore(limit)
                    model_sem = self._model_semaphores[prefix]
                    break

        async def _limited(sample: TestSample) -> EvaluationResult:
            async with self._sample_semaphore:
                if model_sem is not None:
                    async with model_sem:
                        return await self._eval_one_sample(sample, prompt, temperature, model_id)
                return await self._eval_one_sample(sample, prompt, temperature, model_id)

        return await asyncio.gather(*[_limited(s) for s in samples])

    async def _eval_one_sample(
        self,
        sample: TestSample,
        prompt: str,
        temperature: float,
        model_id: Optional[str],
    ) -> EvaluationResult:
        try:
            return await self._evaluate_single_sample(
                prompt, sample, temperature, model_id=model_id
            )
        except Exception as e:
            logger.error(f"  ❌ 评估失败: {e}")
            return EvaluationResult(
                sample_id=sample.sample_id,
                original_text=sample.text,
                rewritten_text="",
                original_ai_score=None,
                rewritten_ai_score=None,
                score_reduction=0,
                success=False,
                error=str(e)
            )

    async def _rewrite_text(self, prompt: str, original_text: str, temperature: float, model_id: Optional[str] = None, targeted_hint: str = "") -> str:
        """使用提示词改写文本（三层架构：预处理 → LLM改写 → 后处理）

        Args:
            prompt: 改写提示词
            original_text: 原始文本
            temperature: LLM温度参数
            model_id: 指定使用的模型ID（可选，None时使用默认路由）
            targeted_hint: 定点消除指令（深区样本统计预检命中时附加，可选）
        """

        # ========== 第1层：规则预处理 ==========
        preprocessed_text, preprocess_logs = preprocess_text(original_text)
        if preprocess_logs:
            logger.debug(f"📝 预处理: {', '.join(preprocess_logs)}")

        # ========== 第2层：LLM改写 ==========
        # 🔧 可选：去锚定重新生成。常规「照着原文改写」会被原文的 token 分布锚定，
        # 输出仍落在 LLM 分布内，检测器照判 AI；先压成事实要点再据要点重写可切断锚定。
        # 实测确定AI占比：常规改写 ~50%，去锚定 ~0-26%。失败一律静默回退常规改写。
        if self.DEANCHOR_ENABLED:
            try:
                from .deanchor_rewrite import DeanchorRewriter

                da_out = await DeanchorRewriter(
                    model_id=model_id, llm_client=self.llm_client
                ).rewrite(
                    preprocessed_text, second_round=True, temperature=temperature,
                    targeted_hint=targeted_hint,
                )
                if da_out and len(da_out.strip()) > len(preprocessed_text) * 0.5:
                    return postprocess_text(da_out.strip())[0]
                logger.warning("   ⚠️ 去锚定产出过短，回退常规改写")
            except Exception as e:
                logger.warning(f"   ⚠️ 去锚定改写失败，回退常规改写: {type(e).__name__}: {str(e)[:100]}")

        user_content = f"请改写以下文本，降低其AI痕迹：\n\n{preprocessed_text}"
        if targeted_hint:
            user_content += "\n" + targeted_hint
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content}
        ]

        # 构建调用参数
        chat_kwargs: Dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "use_cache": False,  # 禁用缓存以获得多样性
        }

        if model_id:
            # 指定模型调用
            chat_kwargs["model"] = model_id
        else:
            # 使用 REWRITE 任务类型（自动选择适合改写的快速模型）
            chat_kwargs["task_type"] = TaskType.REWRITE

        # 🔧 改写链路统一关思考（风格转换任务无深度推理收益；思考常开会吃掉
        #    max_tokens 预算导致 truncation/空响应并大幅拉长响应时间）。
        #    按模型族分发互斥参数：doubao 系拒绝 reasoning_effort+thinking 同传
        #    （400 InvalidParameter 实测），step 系需 reasoning_effort=low
        # disable_fallback：评估场景禁止失败回退——回退模型产出无法归因到
        # 被测模型，污染 A/B 与多模型评测数据（2026-08-23 实测 step 限流时
        # 静默 fallback 到 qwen）
        chat_kwargs["extra_body"] = build_thinking_disabled_extra_body(model_id)
        chat_kwargs["disable_fallback"] = True

        # 🔧 空响应重试：改写模型偶发返回空串，直接判硬失败会批量拖垮变体/基线
        llm_result = ""
        for attempt in range(1, self.REWRITE_MAX_ATTEMPTS + 1):
            llm_result = await self.llm_client.chat(**chat_kwargs) or ""
            if llm_result.strip():
                break
            logger.warning(
                f"   ⚠️ 改写返回空响应（第{attempt}/{self.REWRITE_MAX_ATTEMPTS}次）"
                f" model={model_id or '默认路由'}"
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
        result = await self.ai_detector.detect_ai_content(text)
        return {
            "success": result.get("success", False),
            "ai_score": result.get("ai_score"),
            "label": result.get("label"),
            "error": result.get("error")
        }


