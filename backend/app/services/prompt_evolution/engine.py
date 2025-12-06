"""
提示词进化系统 - 核心引擎

整合所有组件，实现完整的自动化提示词优化循环
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable, List, Dict, Tuple

from .models import (
    PromptVersion,
    EvolutionHistory,
    EvolutionConfig,
    EvaluationResult,
    StopReason
)
from .storage import EvolutionStorage, get_evolution_storage
from .evaluator import PromptEvaluator
from .meta_optimizer import MetaOptimizer
from .test_samples import TestSampleManager
from .genre_detector import get_genre_detector  # 🆕 导入题材检测器

logger = logging.getLogger(__name__)

# 进度回调类型
ProgressCallback = Callable[[str, int, dict], Awaitable[None]]


class PromptEvolutionEngine:
    """提示词进化引擎"""

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        storage: Optional[EvolutionStorage] = None,
        genre: Optional[str] = None  # 🔧 支持指定题材
    ):
        self.config = config or EvolutionConfig()
        self.storage = storage or get_evolution_storage()
        self.evaluator = PromptEvaluator()
        self.meta_optimizer = MetaOptimizer()
        self.sample_manager = TestSampleManager()
        
        # 🆕 题材配置
        self.genre = genre or self.config.genre  # 🔧 当前题材
        if self.genre:
            logger.info(f"🎭 启用题材定制化模式：{self.genre}")
            # 加载题材权重配置
            self.genre_weights = self._get_genre_weights(self.genre)
            self.meta_optimizer.current_genre = self.genre
        else:
            self.genre_weights = None

        # 当前进化状态
        self.history: Optional[EvolutionHistory] = None
        self.is_running = False

        # 🆕 回滚机制：保存最优版本
        self.best_ever_version: Optional[PromptVersion] = None
        self.best_ever_score: float = 100.0
        self.consecutive_worse_count: int = 0  # 连续变差次数

        # 🆕 多维停止条件追踪
        self.score_history: List[float] = []           # AI分数历史
        self.readability_history: List[float] = []     # 可读性历史
        self.writing_history: List[float] = []         # 文笔历史
        self.convergence_count: int = 0                # 收敛计数
        self.oscillation_count: int = 0                # 震荡计数

        # 🔧 探索模式状态
        self.no_improvement_count: int = 0             # 无明显改善次数
        self.exploration_mode: bool = False            # 是否处于探索模式
        self.exploration_attempts: int = 0            # 探索模式尝试次数

        # 🔧 热启动缓存（增强版：基于评分的LRU缓存）
        self._evaluation_cache: Dict[str, Dict] = {}  # prompt_hash -> {score, composite_score, results, access_count, last_access}
        
        # 🆕 A/B测试优化：失败变体记录
        self._failed_variants: Dict[str, int] = {}  # variant_hash -> fail_count
    
    def _get_genre_weights(self, genre: str) -> Dict[str, float]:
        """
        🆕 获取题材权重配置
        
        Args:
            genre: 题材类型
        
        Returns:
            权重配置字典 {"ai_score": 0.4, "readability": 0.3, "writing": 0.2, "fidelity": 0.1}
        """
        # 优先使用配置中的权重
        if self.config.genre_weight_config:
            return self.config.genre_weight_config
        
        # 预设题材权重
        genre_weights = {
            "玄幻": {
                "ai_score": 0.35,      # AI痕迹权重
                "readability": 0.25,   # 可读性权重
                "writing": 0.25,       # 文笔权重
                "fidelity": 0.15       # 保真度权重
            },
            "都市": {
                "ai_score": 0.40,      # 都市文更注重AI痕迹
                "readability": 0.30,   # 可读性重要
                "writing": 0.20,       # 文笔要求适中
                "fidelity": 0.10       # 保真度相对较低
            },
            "言情": {
                "ai_score": 0.30,      # AI痕迹权重适中
                "readability": 0.25,   # 可读性重要
                "writing": 0.35,       # 言情文最注重文笔
                "fidelity": 0.10       # 保真度适中
            },
            "悬疑": {
                "ai_score": 0.35,      # AI痕迹权重
                "readability": 0.30,   # 可读性很重要
                "writing": 0.20,       # 文笔要求适中
                "fidelity": 0.15       # 保真度重要（逻辑严密）
            },
            # 🆕 通用题材（默认权重，适用于多题材混合或未指定题材）
            "通用": {
                "ai_score": 0.35,      # 平衡AI痕迹
                "readability": 0.25,   # 平衡可读性
                "writing": 0.25,       # 平衡文笔
                "fidelity": 0.15       # 平衡保真度
            }
        }
        
        # 如果题材不在预设中，使用通用权重
        weights = genre_weights.get(genre, genre_weights["通用"])
        logger.info(f"🎭 题材「{genre}」权重配置: {weights}")
        return weights
    
    def _calculate_composite_score(
        self, 
        ai_score: float, 
        readability: float, 
        writing: float, 
        fidelity: float = 85.0
    ) -> float:
        """
        🆕 计算综合评分（基于题材权重）
        
        Args:
            ai_score: AI分数（越低越好，0-100）
            readability: 可读性分数（越低越好，0-100）
            writing: 文笔分数（越低越好，0-100）
            fidelity: 保真度分数（越高越好，0-100）
        
        Returns:
            综合评分（越低越好）
        """
        if self.genre_weights:
            # 使用题材权重
            weights = self.genre_weights
        else:
            # 默认使用通用权重
            weights = {"ai_score": 0.35, "readability": 0.25, "writing": 0.25, "fidelity": 0.15}
        
        # 保真度需要反转（100 - fidelity，因为我们希望综合分越低越好）
        fidelity_normalized = 100 - fidelity
        
        composite = (
            ai_score * weights["ai_score"] +
            readability * weights["readability"] +
            writing * weights["writing"] +
            fidelity_normalized * weights["fidelity"]
        )
        
        return composite

    def _get_prompt_hash(self, prompt: str) -> str:
        """🔧 计算提示词的哈希值用于缓存"""
        import hashlib
        return hashlib.md5(prompt.encode()).hexdigest()[:16]

    def _get_cached_evaluation(self, prompt: str) -> Optional[Tuple[float, List]]:
        """🔧 获取缓存的评估结果（更新访问计数）"""
        import time
        prompt_hash = self._get_prompt_hash(prompt)
        cache_entry = self._evaluation_cache.get(prompt_hash)
        
        if cache_entry:
            # 更新访问记录
            cache_entry["access_count"] += 1
            cache_entry["last_access"] = time.time()
            return (cache_entry["score"], cache_entry["results"])
        
        return None

    def _cache_evaluation(self, prompt: str, score: float, results: List, composite_score: Optional[float] = None):
        """🔧 缓存评估结果（基于综合评分保留最优）"""
        import time
        prompt_hash = self._get_prompt_hash(prompt)
        
        # 计算综合评分（如果未提供）
        if composite_score is None:
            composite_score = score
        
        self._evaluation_cache[prompt_hash] = {
            "score": score,
            "composite_score": composite_score,
            "results": results,
            "access_count": 1,
            "last_access": time.time()
        }
        
        # 限制缓存大小（保留评分最好的20个）
        if len(self._evaluation_cache) > 20:
            # 按综合评分排序，移除评分最差的
            sorted_items = sorted(
                self._evaluation_cache.items(),
                key=lambda x: (x[1]["composite_score"], -x[1]["access_count"])  # 评分优先，访问次数其次
            )
            # 移除评分最差的
            worst_key = sorted_items[-1][0]
            removed_score = self._evaluation_cache[worst_key]["composite_score"]
            del self._evaluation_cache[worst_key]
            logger.debug(f"🗑️ 缓存已满，移除评分最差的缓存 (综合评分: {removed_score:.1f})")

    def _check_stop_conditions(
        self,
        ai_score: float,
        readability_score: float,
        writing_score: float
    ) -> StopReason:
        """
        🆕 检查多维停止条件

        Returns:
            StopReason: 包含是否停止、原因、是否需要回滚
        """
        # 记录历史
        self.score_history.append(ai_score)
        self.readability_history.append(readability_score)
        self.writing_history.append(writing_score)

        # === 1. 保护性停止（最高优先级）===
        # 可读性崩坏
        if readability_score < self.config.readability_crash_threshold:
            return StopReason(
                should_stop=True,
                reason_type="protection",
                reason_message=f"🛑 可读性崩坏 ({readability_score:.0f} < {self.config.readability_crash_threshold})",
                should_rollback=True,
                rollback_reason="可读性严重下降，回滚到上一个可用版本"
            )

        # 文笔崩坏
        if writing_score > self.config.writing_crash_threshold:
            return StopReason(
                should_stop=True,
                reason_type="protection",
                reason_message=f"🛑 文笔崩坏 ({writing_score:.0f} > {self.config.writing_crash_threshold})",
                should_rollback=True,
                rollback_reason="文笔过于干涩，回滚到上一个可用版本"
            )

        # === 2. 成功停止（达到理想状态）===
        ai_ok = ai_score <= self.config.early_stop_threshold
        readability_ok = readability_score >= self.config.min_readability_score
        writing_ok = writing_score <= self.config.max_writing_score

        if ai_ok and readability_ok and writing_ok:
            return StopReason(
                should_stop=True,
                reason_type="success",
                reason_message=f"🎉 完美达标！AI:{ai_score:.0f}≤{self.config.early_stop_threshold} "
                              f"可读性:{readability_score:.0f}≥{self.config.min_readability_score} "
                              f"文笔:{writing_score:.0f}≤{self.config.max_writing_score}",
                should_rollback=False
            )

        # === 3. 收敛检查（改善幅度太小）===
        if len(self.score_history) >= 2:
            improvement = self.score_history[-2] - self.score_history[-1]

            if abs(improvement) < self.config.convergence_threshold:
                self.convergence_count += 1
                self.no_improvement_count += 1
            else:
                self.convergence_count = 0
                self.no_improvement_count = 0
                # 有改善时退出探索模式
                if self.exploration_mode:
                    print("   ✅ 探索模式成功找到改善方向，退出探索模式")
                    self.exploration_mode = False
                    self.exploration_attempts = 0

            # 🔧 进入探索模式而非直接停止
            if self.convergence_count >= self.config.convergence_count:
                if not self.exploration_mode and self.exploration_attempts < 2:
                    # 进入探索模式，尝试跳出局部最优
                    self.exploration_mode = True
                    self.exploration_attempts += 1
                    self.convergence_count = 0  # 重置计数
                    print(f"   🔍 进入探索模式（第{self.exploration_attempts}次尝试），使用更高温度和随机策略")
                    # 不返回停止，继续进化
                else:
                    # 探索模式也无法改善，真正停止
                    return StopReason(
                        should_stop=True,
                        reason_type="convergence",
                        reason_message=f"🔄 已收敛：连续{self.config.convergence_count}次改善幅度 < {self.config.convergence_threshold}分（探索模式已尝试{self.exploration_attempts}次）",
                        should_rollback=False
                    )

        # === 4. 震荡停止（分数反复升降）===
        if len(self.score_history) >= 3:
            # 检查最近3次是否升降交替
            diffs = [self.score_history[i+1] - self.score_history[i]
                    for i in range(len(self.score_history)-3, len(self.score_history)-1)]

            if len(diffs) >= 2:
                # 如果符号交替（一正一负或一负一正）
                if (diffs[0] > 0 and diffs[1] < 0) or (diffs[0] < 0 and diffs[1] > 0):
                    self.oscillation_count += 1
                else:
                    self.oscillation_count = 0

                if self.oscillation_count >= self.config.oscillation_count:
                    return StopReason(
                        should_stop=True,
                        reason_type="oscillation",
                        reason_message=f"🔄 策略震荡：分数连续{self.oscillation_count}次升降交替，无法稳定优化",
                        should_rollback=False
                    )

        # 未触发任何停止条件
        return StopReason(should_stop=False)

    def _reset_stop_tracking(self):
        """重置停止条件追踪状态"""
        self.score_history.clear()
        self.readability_history.clear()
        self.writing_history.clear()
        self.convergence_count = 0
        self.oscillation_count = 0
        self.no_improvement_count = 0
        self.exploration_mode = False
        self.exploration_attempts = 0
        self.reverse_optimization_mode = False  # 🆕 反向优化模式标志

    def _get_current_temperature(self) -> float:
        """🔧 获取当前温度（探索模式使用更高温度）"""
        if self.exploration_mode:
            return self.config.exploration_temperature
        return self.config.temperature

    def _reset_after_rollback(self):
        """
        🔧 回滚后重置状态（增强版）

        彻底清除失败方向的记忆，引入随机扰动以跳出局部最优
        """
        import random

        # 1. 清除所有历史分析（而非只保留最后2条）
        self.meta_optimizer.previous_analyses.clear()
        logger.info("🔄 回滚：清除所有历史分析记录")

        # 2. 重置收敛和震荡计数
        self.convergence_count = 0
        self.oscillation_count = 0
        self.no_improvement_count = 0

        # 3. 清除部分分数历史（保留最近2个作为参考）
        if len(self.score_history) > 2:
            self.score_history = self.score_history[-2:]
        if len(self.readability_history) > 2:
            self.readability_history = self.readability_history[-2:]
        if len(self.writing_history) > 2:
            self.writing_history = self.writing_history[-2:]

        # 4. 🔧 引入随机扰动：随机移除一些"无效策略"记录
        # 这样可以让系统重新尝试之前被标记为无效的策略
        if self.meta_optimizer.experience.ineffective_strategies:
            num_to_remove = min(3, len(self.meta_optimizer.experience.ineffective_strategies) // 2)
            if num_to_remove > 0:
                for _ in range(num_to_remove):
                    idx = random.randint(0, len(self.meta_optimizer.experience.ineffective_strategies) - 1)
                    removed = self.meta_optimizer.experience.ineffective_strategies.pop(idx)
                    logger.info(f"🎲 随机移除无效策略记录: {removed[:50]}...")

        # 5. 🆕 随机移除部分经验约束（探索模式核心）
        # 移除部分有效策略和失败原因，给系统更多试错空间
        if self.meta_optimizer.experience.effective_strategies:
            num_to_remove = max(1, len(self.meta_optimizer.experience.effective_strategies) // 3)
            for _ in range(num_to_remove):
                if self.meta_optimizer.experience.effective_strategies:
                    idx = random.randint(0, len(self.meta_optimizer.experience.effective_strategies) - 1)
                    removed = self.meta_optimizer.experience.effective_strategies.pop(idx)
                    logger.info(f"🎲 探索模式：随机移除有效策略约束: {removed[:50]}...")
        
        if self.meta_optimizer.experience.failure_reasons:
            num_to_remove = max(1, len(self.meta_optimizer.experience.failure_reasons) // 3)
            for _ in range(num_to_remove):
                if self.meta_optimizer.experience.failure_reasons:
                    idx = random.randint(0, len(self.meta_optimizer.experience.failure_reasons) - 1)
                    removed = self.meta_optimizer.experience.failure_reasons.pop(idx)
                    logger.info(f"🎲 探索模式：随机移除失败原因约束: {removed[:50]}...")

        # 6. 🆕 决定是否启用反向优化（50%概率）
        self.reverse_optimization_mode = random.random() < 0.5
        if self.reverse_optimization_mode:
            logger.info("🔀 启用反向优化模式：尝试与历史策略相反的方向")
        
        # 7. 进入探索模式（使用更高温度）
        self.exploration_mode = True
        self.exploration_attempts += 1
        logger.info(f"🔍 回滚后进入探索模式（第{self.exploration_attempts}次），使用更高温度尝试新方向")

    def _get_dynamic_variant_count(self, iteration: int) -> int:
        """
        🔧 动态变体生成：根据进化阶段调整变体数量

        策略：
        - 早期（前1/3迭代）：生成更多变体（4-5个），广泛探索
        - 中期（中间1/3）：正常数量（3个），平衡探索与利用
        - 后期（后1/3）：减少变体（2个），精细调优
        - 探索模式：增加变体数量
        """
        max_iter = self.config.max_iterations
        base_count = self.config.ab_test_variant_count

        # 探索模式时增加变体
        if self.exploration_mode:
            return min(base_count + 2, 5)

        # 根据进化阶段调整
        progress_ratio = iteration / max_iter

        if progress_ratio < 0.33:
            # 早期：多探索
            return min(base_count + 1, 5)
        elif progress_ratio < 0.66:
            # 中期：正常
            return base_count
        else:
            # 后期：精细调优
            return max(base_count - 1, 2)

    async def run_evolution(
        self,
        on_progress: Optional[ProgressCallback] = None
    ) -> EvolutionHistory:
        """
        运行进化优化流程
        
        Args:
            on_progress: 进度回调函数 (message, progress_percent, data)
            
        Returns:
            进化历史记录
        """
        if self.is_running:
            raise RuntimeError("进化引擎正在运行中")
        
        self.is_running = True
        
        # 初始化历史记录
        self.history = EvolutionHistory(
            target_score=self.config.target_score,
            max_iterations=self.config.max_iterations
        )
        
        try:
            # 🆕 重置停止条件追踪
            self._reset_stop_tracking()

            print("🚀🚀🚀 [进化引擎] 开始提示词进化优化...")
            logger.info("🚀 开始提示词进化优化")
            await self._notify_progress(on_progress, "🚀 开始提示词进化优化", 0, {})

            # 重置经验库并加载历史经验（跨批次传承）
            self.meta_optimizer.reset_experience()
            historical_reports = self.storage.get_all_experience_reports()
            if historical_reports:
                loaded_count = self.meta_optimizer.load_historical_experience(historical_reports)
                print(f"📚 从历史批次加载经验: {loaded_count} 条")
                await self._notify_progress(on_progress, f"📚 加载历史经验 {loaded_count} 条", 2, {})
            else:
                print("📚 无历史经验，从零开始")

            # 获取测试样本
            samples = self.sample_manager.get_samples(self.config.samples_per_iteration)
            print(f"📝 获取到 {len(samples)} 个测试样本")
            
            # 🆕 自动检测题材（如果未指定）
            if not self.genre:
                print("🔍 未指定题材，开始自动检测...")
                detector = get_genre_detector()
                self.genre = detector.detect_from_samples(samples)
                print(f"🎭 自动检测到题材: {self.genre}")
                
                # 加载题材权重
                self.genre_weights = self._get_genre_weights(self.genre)
                self.meta_optimizer.current_genre = self.genre
                
                await self._notify_progress(on_progress, f"🎭 检测到题材: {self.genre}", 3, {"genre": self.genre})

            # 尝试使用历史最佳提示词作为起点
            initial_prompt = self._get_best_starting_prompt()
            current_version = PromptVersion(
                prompt_text=initial_prompt,
                iteration=0
            )
            
            # 🔧 热启动：检查是否有缓存的评估结果
            cached = self._get_cached_evaluation(initial_prompt)
            if cached:
                avg_score, results = cached
                print(f"🔥 热启动：使用缓存的评估结果，平均得分: {avg_score:.1f}")
                await self._notify_progress(on_progress, f"🔥 热启动：使用缓存结果 {avg_score:.1f}", 5, {})
            else:
                # 评估初始版本
                print("📊 开始评估初始提示词...")
                await self._notify_progress(on_progress, "📊 评估初始提示词...", 5, {})
                avg_score, results = await self.evaluator.evaluate_prompt(
                    initial_prompt, samples, self.config.temperature
                )
                print(f"📊 初始评估完成，平均得分: {avg_score:.1f}")
                # 缓存结果（传入综合评分）
                # 此时还未计算综合评分，先用AI分数
                self._cache_evaluation(initial_prompt, avg_score, results, composite_score=avg_score)
            current_version.avg_ai_score = avg_score
            current_version.evaluation_results = results
            current_version.avg_score_reduction = self._calc_avg_reduction(results)

            # 🔧 计算初始版本的多维评分（与迭代版本一致）
            readability_scores = []
            writing_scores = []
            composite_scores = []
            for r in results:
                if r.success and r.rewritten_multi_score:
                    readability_scores.append(r.rewritten_multi_score.get("readability_score", 80))
                    writing_scores.append(r.rewritten_multi_score.get("writing_score", 50))
                    composite_scores.append(r.rewritten_multi_score.get("composite_score", avg_score))
            current_version.avg_readability = sum(readability_scores) / len(readability_scores) if readability_scores else 80
            current_version.avg_writing = sum(writing_scores) / len(writing_scores) if writing_scores else 50
            current_version.avg_composite_score = sum(composite_scores) / len(composite_scores) if composite_scores else avg_score
            print(f"📖 初始版本多维评分 - 可读性: {current_version.avg_readability:.1f}, 文笔: {current_version.avg_writing:.1f}, 综合: {current_version.avg_composite_score:.1f}")

            self._update_best_versions(current_version)
            self.history.all_versions.append(current_version)
            self._save_progress()
            
            await self._notify_progress(
                on_progress,
                f"初始得分: {avg_score:.1f}",
                10,
                {"iteration": 0, "score": avg_score}
            )
            
            # 迭代优化
            for iteration in range(1, self.config.max_iterations + 1):
                print(f"\n🔄🔄🔄 [进化引擎] 开始迭代 {iteration}/{self.config.max_iterations}")
                self.history.current_iteration = iteration
                progress = 10 + int(80 * iteration / self.config.max_iterations)

                # 注意：多维停止条件在迭代结束时检查（_check_stop_conditions）
                # 这里只做简单的迭代进度通知
                await self._notify_progress(
                    on_progress,
                    f"🔄 迭代 {iteration}/{self.config.max_iterations}：优化提示词...",
                    progress,
                    {"iteration": iteration}
                )

                # 元优化：生成改进的提示词
                print(f"🧠 调用元优化器生成改进提示词...")
                # 🆕 传入探索模式和反向优化标志
                improved_prompt, analysis = await self.meta_optimizer.optimize_prompt(
                    current_version,
                    self.config.target_score,
                    self.history.all_versions,
                    exploration_mode=self.exploration_mode,
                    reverse_optimization=self.reverse_optimization_mode
                )
                if self.exploration_mode:
                    mode_info = "🔍探索模式"
                    if self.reverse_optimization_mode:
                        mode_info += " + 🔀反向优化"
                    print(f"{mode_info} 元优化完成，分析: {analysis[:100]}...")
                else:
                    print(f"🧠 元优化完成，分析: {analysis[:100]}...")

                # 🔧 A/B测试：根据配置间隔生成变体进行对比
                best_prompt = improved_prompt
                best_analysis = analysis
                best_score = float('inf')

                ab_interval = self.config.ab_test_interval
                if iteration % ab_interval == 0 and iteration > 0:
                    print(f"🔬 进行A/B测试...")
                    await self._notify_progress(
                        on_progress,
                        f"🔬 迭代 {iteration}: 进行A/B变体测试...",
                        progress + 2,
                        {"iteration": iteration, "ab_test": True}
                    )

                    # 🔧 动态变体生成：根据进化阶段调整数量
                    variant_count = self._get_dynamic_variant_count(iteration)
                    # 🆕 传入探索模式标志
                    variants = await self.meta_optimizer.generate_prompt_variants(
                        improved_prompt, 
                        variant_count,
                        exploration_mode=self.exploration_mode
                    )
                    
                    # 🆕 过滤失败变体（失败次数>=3的变体）
                    filtered_variants = []
                    skipped_count = 0
                    for variant_prompt, variant_desc in variants:
                        if variant_prompt:
                            variant_hash = self._get_prompt_hash(variant_prompt)
                            fail_count = self._failed_variants.get(variant_hash, 0)
                            if fail_count >= 3:
                                print(f"   ⏭️ 跳过失败变体（已失败{fail_count}次）: {variant_desc}")
                                skipped_count += 1
                            else:
                                filtered_variants.append((variant_prompt, variant_desc))
                    
                    if not filtered_variants:
                        print(f"   ℹ️ 所有变体均已失败，跳过A/B测试")
                    else:
                        if skipped_count > 0:
                            print(f"   🛡️ 已过滤 {skipped_count} 个失败变体")
                        
                        # 🔧 使用配置的样本数进行A/B评估
                        ab_sample_count = min(self.config.ab_test_sample_count, len(samples))
                        ab_samples = samples[:ab_sample_count]
                        print(f"   📋 使用 {ab_sample_count} 个样本进行A/B评估（{len(filtered_variants)}个有效变体）")

                        # 🆕 评估原始版本（优先使用缓存）
                        cached_orig = self._get_cached_evaluation(improved_prompt)
                        if cached_orig:
                            orig_score, orig_results = cached_orig
                            print(f"   📊 原始版本得分: {orig_score:.1f} (💾缓存)")
                        else:
                            orig_score, orig_results = await self.evaluator.evaluate_prompt(
                                improved_prompt, ab_samples, self.config.temperature
                            )
                            print(f"   📊 原始版本得分: {orig_score:.1f}")
                            # 缓存原始版本评估结果
                            self._cache_evaluation(improved_prompt, orig_score, orig_results)
                        
                        best_score = orig_score

                        # 收集所有变体得分用于统计
                        all_scores = [(orig_score, improved_prompt, "原始版本")]

                        # 🆕 评估变体（优先使用缓存）
                        for i, (variant_prompt, variant_desc) in enumerate(filtered_variants, 1):
                            variant_hash = self._get_prompt_hash(variant_prompt)
                            
                            # 检查缓存
                            cached_var = self._get_cached_evaluation(variant_prompt)
                            if cached_var:
                                var_score, var_results = cached_var
                                print(f"   📊 变体{i}得分: {var_score:.1f} ({variant_desc}) (💾缓存)")
                            else:
                                var_score, var_results = await self.evaluator.evaluate_prompt(
                                    variant_prompt, ab_samples, self.config.temperature
                                )
                                print(f"   📊 变体{i}得分: {var_score:.1f} ({variant_desc})")
                                # 缓存变体评估结果
                                self._cache_evaluation(variant_prompt, var_score, var_results)
                            
                            all_scores.append((var_score, variant_prompt, variant_desc))

                        # 🔧 选择最佳版本（需要满足显著性差异）
                        all_scores.sort(key=lambda x: x[0])
                        winner_score, winner_prompt, winner_desc = all_scores[0]

                        # 检查是否有显著改善
                        score_diff = orig_score - winner_score
                        if score_diff >= self.config.ab_test_min_diff:
                            best_score = winner_score
                            best_prompt = winner_prompt
                            best_analysis = f"{analysis} [A/B胜出: {winner_desc}, ↓{score_diff:.1f}分]"
                            print(f"   ✨ {winner_desc}显著胜出! (差异: {score_diff:.1f}分)")
                        elif winner_prompt != improved_prompt:
                            print(f"   ➡️ 差异不显著({score_diff:.1f}<{self.config.ab_test_min_diff})，保持原版本")
                            # 🆕 记录失败变体
                            for var_score, var_prompt, var_desc in all_scores[1:]:
                                if var_prompt != improved_prompt:  # 排除原始版本
                                    var_hash = self._get_prompt_hash(var_prompt)
                                    self._failed_variants[var_hash] = self._failed_variants.get(var_hash, 0) + 1
                                    fail_count = self._failed_variants[var_hash]
                                    if fail_count >= 3:
                                        print(f"   ⚠️ {var_desc}已失败{fail_count}次，将被标记")

                # 创建新版本
                new_version = PromptVersion(
                    prompt_text=best_prompt,
                    iteration=iteration,
                    parent_version_id=current_version.version_id,
                    analysis=best_analysis
                )

                # 评估新版本（完整评估）
                # 🔧 使用动态温度（探索模式时使用更高温度）
                current_temp = self._get_current_temperature()
                if self.exploration_mode:
                    print(f"   🔍 探索模式：使用温度 {current_temp}")
                avg_score, results = await self.evaluator.evaluate_prompt(
                    best_prompt, samples, current_temp
                )
                new_version.avg_ai_score = avg_score
                new_version.evaluation_results = results
                new_version.avg_score_reduction = self._calc_avg_reduction(results)

                # 🆕 提取可读性和文笔分数
                readability_scores = []
                writing_scores = []
                for r in results:
                    if r.success and r.rewritten_multi_score:
                        readability_scores.append(r.rewritten_multi_score.get("readability_score", 80))
                        writing_scores.append(r.rewritten_multi_score.get("writing_score", 50))
                avg_readability = sum(readability_scores) / len(readability_scores) if readability_scores else 80
                avg_writing = sum(writing_scores) / len(writing_scores) if writing_scores else 50

                # 🔧 计算并保存综合评分
                composite_scores = []
                for r in results:
                    if r.success and r.rewritten_multi_score:
                        composite_scores.append(r.rewritten_multi_score.get("composite_score", avg_score))
                avg_composite = sum(composite_scores) / len(composite_scores) if composite_scores else avg_score

                new_version.avg_readability = avg_readability
                new_version.avg_writing = avg_writing
                new_version.avg_composite_score = avg_composite
                
                # 🆕 添加题材标签
                if self.genre:
                    new_version.genre = self.genre
                    new_version.genre_optimized = True

                print(f"   📖 平均可读性: {avg_readability:.1f}, 平均文笔: {avg_writing:.1f}, 综合评分: {avg_composite:.1f}", flush=True)
                if self.genre:
                    print(f"   🎭 题材标签: {self.genre}", flush=True)

                # 🆕 缓存评估结果（传入综合评分以便优化缓存策略）
                self._cache_evaluation(best_prompt, avg_score, results, composite_score=avg_composite)

                # 🆕 多维停止条件检查
                stop_reason = self._check_stop_conditions(avg_score, avg_readability, avg_writing)

                if stop_reason.should_stop:
                    print(f"\n   {stop_reason.reason_message}", flush=True)

                    if stop_reason.should_rollback and self.best_ever_version:
                        print(f"   🔄 {stop_reason.rollback_reason}", flush=True)
                        # 回滚到最优版本
                        current_version = self.best_ever_version
                        self._update_best_versions(current_version)
                        self.history.all_versions.append(new_version)  # 仍记录当前版本
                        self._save_progress()

                    await self._notify_progress(
                        on_progress,
                        stop_reason.reason_message,
                        100,
                        {"stop_type": stop_reason.reason_type, "stop_reason": stop_reason.reason_message}
                    )
                    break

                # 🆕 回滚机制：检测是否需要回滚（基于连续退化）
                should_rollback = False

                # 🆕 综合判断：AI分数下降 + 可读性保持 + 文笔保持
                readability_ok = avg_readability >= self.config.readability_crash_threshold
                writing_ok = avg_writing <= self.config.writing_crash_threshold
                quality_ok = readability_ok and writing_ok

                # 🔧 修复：区分"显著改善"、"保持相当"、"退化"三种状态
                SIGNIFICANT_IMPROVEMENT_THRESHOLD = 2.0  # 显著改善阈值（分数下降超过此值）
                EQUIVALENT_THRESHOLD = 1.0  # 相当阈值（分数变化在此范围内视为相当）

                score_diff = self.best_ever_score - avg_score  # 正值表示改善，负值表示退化

                is_significantly_better = score_diff >= SIGNIFICANT_IMPROVEMENT_THRESHOLD and quality_ok
                is_equivalent = abs(score_diff) < EQUIVALENT_THRESHOLD and quality_ok
                is_better = score_diff > 0 and quality_ok  # 任何程度的改善

                if is_significantly_better:
                    # 新版本显著更好，更新最优记录
                    self.best_ever_score = avg_score
                    self.best_ever_version = new_version
                    self.consecutive_worse_count = 0
                    print(f"   🏆 新的最优版本! AI:{avg_score:.1f} 可读性:{avg_readability:.1f} 文笔:{avg_writing:.1f} (↓{score_diff:.1f})", flush=True)
                elif is_better:
                    # 有改善但不显著，仍更新最优记录
                    self.best_ever_score = avg_score
                    self.best_ever_version = new_version
                    self.consecutive_worse_count = 0
                    print(f"   ✅ 略有改善 AI:{avg_score:.1f} 可读性:{avg_readability:.1f} 文笔:{avg_writing:.1f} (↓{score_diff:.1f})", flush=True)
                elif is_equivalent:
                    # 🔧 新增：保持相当状态，不累加退化计数，但也不更新最优版本
                    print(f"   ➡️ 保持相当 AI:{avg_score:.1f} 可读性:{avg_readability:.1f} 文笔:{avg_writing:.1f} (±{abs(score_diff):.1f})", flush=True)
                    # 不累加 consecutive_worse_count，给系统更多探索机会
                else:
                    # 新版本确实变差或质量不合格
                    self.consecutive_worse_count += 1
                    if not readability_ok:
                        print(f"   ⚠️ 可读性不合格({avg_readability:.1f})，连续{self.consecutive_worse_count}次未改善", flush=True)
                    elif not writing_ok:
                        print(f"   ⚠️ 文笔不合格({avg_writing:.1f})，连续{self.consecutive_worse_count}次未改善", flush=True)
                    else:
                        degradation = avg_score - self.best_ever_score
                        print(f"   ⚠️ 效果变差 (+{degradation:.1f}分)，连续{self.consecutive_worse_count}次", flush=True)

                    # 连续3次变差，触发回滚
                    if self.consecutive_worse_count >= 3 and self.best_ever_version:
                        should_rollback = True
                        print(f"   🔄 触发回滚！恢复到最优版本 (得分: {self.best_ever_score:.1f})", flush=True)
                        await self._notify_progress(
                            on_progress,
                            f"🔄 连续退化，回滚到最优版本 (得分: {self.best_ever_score:.1f})",
                            progress + 3,
                            {"rollback": True, "best_score": self.best_ever_score}
                        )

                if should_rollback and self.best_ever_version:
                    # 回滚到最优版本
                    current_version = self.best_ever_version
                    self.consecutive_worse_count = 0
                    # 添加回滚记录
                    rollback_note = f"[回滚] 从 {avg_score:.1f} 回滚到 {self.best_ever_score:.1f}"
                    new_version.analysis = f"{best_analysis} {rollback_note}"

                    # 🔧 增强版回滚重置：彻底清除失败方向记忆
                    self._reset_after_rollback()
                else:
                    current_version = new_version

                self._update_best_versions(new_version)
                self.history.all_versions.append(new_version)
                self._save_progress()

                await self._notify_progress(
                    on_progress,
                    f"迭代 {iteration} 完成: 得分 {avg_score:.1f}",
                    progress + 5,
                    {"iteration": iteration, "score": avg_score, "analysis": best_analysis}
                )
            
            # 完成
            self.history.status = "completed"
            self.history.completed_at = datetime.now().isoformat()
            self._save_progress()

            # 保存经验报告
            experience_report = self.meta_optimizer.get_experience_report()
            self._save_experience_report(experience_report)

            best_score = self.history.best_versions[0].avg_ai_score if self.history.best_versions else 100
            await self._notify_progress(
                on_progress,
                f"✅ 进化完成！最佳得分: {best_score:.1f}",
                100,
                {
                    "best_score": best_score,
                    "total_iterations": self.history.current_iteration,
                    "experience_report": experience_report
                }
            )

            return self.history
            
        except Exception as e:
            logger.error(f"❌ 进化过程出错: {e}")
            if self.history:
                self.history.status = "failed"
                self.history.error_message = str(e)
                self._save_progress()
            raise
        finally:
            self.is_running = False
    
    def _update_best_versions(self, version: PromptVersion) -> None:
        """更新最佳版本列表（保留前N个）"""
        self.history.best_versions.append(version)
        self.history.best_versions.sort(key=lambda v: v.avg_ai_score)
        self.history.best_versions = self.history.best_versions[:self.config.keep_top_n]
        
        # 同时保存到文件
        self.storage.save_best_prompts(self.history.best_versions, self.config.keep_top_n)
    
    def _calc_avg_reduction(self, results: List[EvaluationResult]) -> float:
        """计算平均得分下降"""
        valid = [r for r in results if r.success]
        if not valid:
            return 0.0
        return sum(r.score_reduction for r in valid) / len(valid)
    
    def _save_progress(self) -> None:
        """保存进化进度"""
        if self.history:
            self.storage.save_evolution_history(self.history)

    def _save_experience_report(self, report: dict) -> None:
        """保存经验报告"""
        if self.history:
            self.storage.save_experience_report(self.history.evolution_id, report)

    def _get_best_starting_prompt(self) -> str:
        """
        获取最佳起始提示词

        🔧 优先级调整（使用综合评分选择效果最好的）：
        1. 🆕 同题材的历史最佳提示词（综合评分最低的）- 最高优先级
        2. 历史最佳提示词（综合评分最低的）- 优先使用实际效果最好的
        3. 已批准的提示词 - 作为备选
        4. 默认初始提示词

        说明：使用综合评分（而非单纯AI分数）来选择起点，
        综合评分考虑了AI检测、可读性、文笔等多个维度。
        """
        best_score = float('inf')
        best_prompt = None
        best_source = ""
        best_version_id = ""
        best_ai_score = 100.0

        # 1. 🆕 检查历史最佳提示词（优先选择同题材）
        best_prompts = self.storage.load_best_prompts()
        if best_prompts:
            # 🆕 先筛选同题材的提示词
            if self.genre:
                same_genre_prompts = [p for p in best_prompts if p.genre == self.genre]
                if same_genre_prompts:
                    # 选择同题材中综合评分最低（效果最好）的
                    history_best = min(same_genre_prompts, key=lambda p: p.avg_composite_score)
                    logger.debug(f"🎭 同题材「{self.genre}」最佳: {history_best.version_id}, 综合评分: {history_best.avg_composite_score}, AI分数: {history_best.avg_ai_score}")
                    if history_best.avg_composite_score < best_score and history_best.avg_ai_score < 80:
                        best_score = history_best.avg_composite_score
                        best_ai_score = history_best.avg_ai_score
                        best_prompt = history_best.prompt_text
                        best_source = f"同题材「{self.genre}」最佳"
                        best_version_id = history_best.version_id
                else:
                    logger.debug(f"🎭 没有同题材「{self.genre}」的历史提示词")
            
            # 如果没有找到同题材的，或者没有指定题材，选择所有历史中最好的
            if not best_prompt:
                # 🔧 选择综合评分最低（效果最好）的
                history_best = min(best_prompts, key=lambda p: p.avg_composite_score)
                logger.debug(f"📊 历史最佳: {history_best.version_id}, 综合评分: {history_best.avg_composite_score}, AI分数: {history_best.avg_ai_score}")
                if history_best.avg_composite_score < best_score and history_best.avg_ai_score < 80:
                    best_score = history_best.avg_composite_score
                    best_ai_score = history_best.avg_ai_score
                    best_prompt = history_best.prompt_text
                    best_source = "历史最佳"
                    best_version_id = history_best.version_id
        else:
            logger.debug("📊 没有历史最佳提示词")

        # 2. 检查已批准的提示词（仅当比历史最佳更好时使用）
        approved = self.storage.get_latest_approved_prompt()
        if approved and approved.get("prompt_text"):
            # 🔧 优先使用综合评分，如果没有则回退到AI分数
            approved_score = approved.get("avg_composite_score", approved.get("avg_ai_score", 100))
            logger.debug(f"📊 已批准: {approved.get('version_id')}, 综合评分: {approved_score}, AI分数: {approved.get('avg_ai_score')}")
            if approved_score < best_score:
                best_score = approved_score
                best_ai_score = approved.get("avg_ai_score", 100)
                best_prompt = approved["prompt_text"]
                best_source = "已批准"
                best_version_id = approved.get("version_id", "?")
        else:
            logger.debug("📊 没有已批准提示词")

        # 使用找到的最佳提示词
        if best_prompt:
            print(f"✨ 使用{best_source}提示词作为起点 (综合评分: {best_score:.1f}, AI分数: {best_ai_score:.1f})")
            logger.info(f"✨ 使用{best_source}提示词: {best_version_id}, 综合评分: {best_score}, AI分数: {best_ai_score}")
            return best_prompt

        # 3. 使用默认初始提示词（🔧 支持按题材定制）
        if self.genre:
            print(f"📝 使用默认初始提示词（题材: {self.genre}）")
        else:
            print("📝 使用默认初始提示词")
        return self.meta_optimizer.get_initial_prompt(genre=self.genre)

    async def _notify_progress(
        self,
        callback: Optional[ProgressCallback],
        message: str,
        progress: int,
        data: dict
    ) -> None:
        """通知进度"""
        logger.info(f"[{progress}%] {message}")
        if callback:
            try:
                await callback(message, progress, data)
            except Exception as e:
                logger.warning(f"进度回调失败: {e}")


async def run_evolution(
    config: Optional[EvolutionConfig] = None,
    on_progress: Optional[ProgressCallback] = None
) -> EvolutionHistory:
    """便捷函数：运行进化优化"""
    engine = PromptEvolutionEngine(config)
    return await engine.run_evolution(on_progress)

