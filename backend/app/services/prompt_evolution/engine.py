"""
提示词进化系统 - 核心引擎

整合所有组件，实现完整的自动化提示词优化循环
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable, List

from .models import (
    PromptVersion,
    EvolutionHistory,
    EvolutionConfig,
    EvaluationResult
)
from .storage import EvolutionStorage, get_evolution_storage
from .evaluator import PromptEvaluator
from .meta_optimizer import MetaOptimizer
from .test_samples import TestSampleManager

logger = logging.getLogger(__name__)

# 进度回调类型
ProgressCallback = Callable[[str, int, dict], Awaitable[None]]


class PromptEvolutionEngine:
    """提示词进化引擎"""

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        storage: Optional[EvolutionStorage] = None
    ):
        self.config = config or EvolutionConfig()
        self.storage = storage or get_evolution_storage()
        self.evaluator = PromptEvaluator()
        self.meta_optimizer = MetaOptimizer()
        self.sample_manager = TestSampleManager()

        # 当前进化状态
        self.history: Optional[EvolutionHistory] = None
        self.is_running = False

        # 🆕 回滚机制：保存最优版本
        self.best_ever_version: Optional[PromptVersion] = None
        self.best_ever_score: float = 100.0
        self.consecutive_worse_count: int = 0  # 连续变差次数
    
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

            # 尝试使用历史最佳提示词作为起点
            initial_prompt = self._get_best_starting_prompt()
            current_version = PromptVersion(
                prompt_text=initial_prompt,
                iteration=0
            )
            
            # 评估初始版本
            print("📊 开始评估初始提示词...")
            await self._notify_progress(on_progress, "📊 评估初始提示词...", 5, {})
            avg_score, results = await self.evaluator.evaluate_prompt(
                initial_prompt, samples, self.config.temperature
            )
            print(f"📊 初始评估完成，平均得分: {avg_score:.1f}")
            current_version.avg_ai_score = avg_score
            current_version.evaluation_results = results
            current_version.avg_score_reduction = self._calc_avg_reduction(results)
            
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

                # 检查是否达标
                if current_version.avg_ai_score <= self.config.early_stop_threshold:
                    print(f"🎉 提前达标！得分 {current_version.avg_ai_score:.1f}")
                    await self._notify_progress(
                        on_progress,
                        f"🎉 提前达标！得分 {current_version.avg_ai_score:.1f} ≤ {self.config.early_stop_threshold}",
                        100,
                        {"early_stop": True}
                    )
                    break

                await self._notify_progress(
                    on_progress,
                    f"🔄 迭代 {iteration}/{self.config.max_iterations}：优化提示词...",
                    progress,
                    {"iteration": iteration}
                )

                # 元优化：生成改进的提示词
                print(f"🧠 调用元优化器生成改进提示词...")
                improved_prompt, analysis = await self.meta_optimizer.optimize_prompt(
                    current_version,
                    self.config.target_score,
                    self.history.all_versions
                )
                print(f"🧠 元优化完成，分析: {analysis[:100]}...")

                # 🆕 A/B测试：每3轮生成变体进行对比
                best_prompt = improved_prompt
                best_analysis = analysis
                best_score = float('inf')

                if iteration % 3 == 0 and iteration > 0:
                    print(f"🔬 进行A/B测试...")
                    await self._notify_progress(
                        on_progress,
                        f"🔬 迭代 {iteration}: 进行A/B变体测试...",
                        progress + 2,
                        {"iteration": iteration, "ab_test": True}
                    )

                    # 生成变体
                    variants = await self.meta_optimizer.generate_prompt_variants(improved_prompt, 2)

                    # 🆕 使用2-3个样本进行A/B评估（更具代表性）
                    ab_sample_count = min(3, len(samples))
                    ab_samples = samples[:ab_sample_count]
                    print(f"   📋 使用 {ab_sample_count} 个样本进行A/B评估")

                    # 评估原始版本
                    orig_score, orig_results = await self.evaluator.evaluate_prompt(
                        improved_prompt, ab_samples, self.config.temperature
                    )
                    best_score = orig_score
                    print(f"   📊 原始版本得分: {orig_score:.1f}")

                    # 评估变体
                    for i, (variant_prompt, variant_desc) in enumerate(variants, 1):
                        if variant_prompt:
                            var_score, var_results = await self.evaluator.evaluate_prompt(
                                variant_prompt, ab_samples, self.config.temperature
                            )
                            print(f"   📊 变体{i}得分: {var_score:.1f} ({variant_desc})")

                            if var_score < best_score:
                                best_score = var_score
                                best_prompt = variant_prompt
                                best_analysis = f"{analysis} [A/B胜出: {variant_desc}]"
                                print(f"   ✨ 变体{i}胜出!")

                # 创建新版本
                new_version = PromptVersion(
                    prompt_text=best_prompt,
                    iteration=iteration,
                    parent_version_id=current_version.version_id,
                    analysis=best_analysis
                )

                # 评估新版本（完整评估）
                avg_score, results = await self.evaluator.evaluate_prompt(
                    best_prompt, samples, self.config.temperature
                )
                new_version.avg_ai_score = avg_score
                new_version.evaluation_results = results
                new_version.avg_score_reduction = self._calc_avg_reduction(results)

                # 🆕 计算可读性平均分
                readability_scores = []
                for r in results:
                    if r.success and r.rewritten_multi_score:
                        readability_scores.append(r.rewritten_multi_score.get("readability_score", 80))
                avg_readability = sum(readability_scores) / len(readability_scores) if readability_scores else 80

                print(f"   📖 平均可读性: {avg_readability:.1f}", flush=True)

                # 🆕 可读性保护：如果可读性严重下降，拒绝该版本
                readability_rejection = False
                if avg_readability < 50:
                    readability_rejection = True
                    print(f"   🚫 可读性过低({avg_readability:.1f})，拒绝该版本", flush=True)
                    logger.warning(f"版本被拒绝: 可读性分数 {avg_readability:.1f} 低于阈值50")

                # 🆕 回滚机制：检测是否需要回滚
                should_rollback = False

                # 🆕 综合判断：AI分数下降 + 可读性保持
                is_better = avg_score < self.best_ever_score and not readability_rejection

                if is_better:
                    # 新版本更好，更新最优记录
                    self.best_ever_score = avg_score
                    self.best_ever_version = new_version
                    self.consecutive_worse_count = 0
                    print(f"   🏆 新的最优版本! AI得分: {avg_score:.1f}, 可读性: {avg_readability:.1f}", flush=True)
                else:
                    # 新版本变差或可读性不合格
                    self.consecutive_worse_count += 1
                    if readability_rejection:
                        print(f"   ⚠️ 可读性不合格，连续{self.consecutive_worse_count}次未改善", flush=True)
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
                    # 🆕 回滚后重置历史分析，避免陷入同样的优化方向
                    self.meta_optimizer.previous_analyses = self.meta_optimizer.previous_analyses[-2:]
                    logger.info("🔄 回滚后重置部分历史分析，尝试新方向")
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
        获取最佳起始提示词（优先使用历史最佳）

        优先级：
        1. 已批准的提示词
        2. 历史最佳提示词（得分最低的）
        3. 默认初始提示词
        """
        # 1. 检查是否有已批准的提示词
        approved = self.storage.get_latest_approved_prompt()
        if approved and approved.get("prompt_text"):
            print(f"✨ 使用已批准的提示词作为起点 (得分: {approved.get('avg_ai_score', '?')})")
            logger.info(f"✨ 使用已批准提示词: {approved.get('version_id')}")
            return approved["prompt_text"]

        # 2. 检查历史最佳提示词
        best_prompts = self.storage.load_best_prompts()
        if best_prompts:
            # 选择得分最低（效果最好）的
            best = min(best_prompts, key=lambda p: p.avg_ai_score)
            if best.avg_ai_score < 80:  # 只有足够好的才使用
                print(f"✨ 使用历史最佳提示词作为起点 (得分: {best.avg_ai_score:.1f})")
                logger.info(f"✨ 使用历史最佳提示词: {best.version_id}, 得分: {best.avg_ai_score}")
                return best.prompt_text

        # 3. 使用默认初始提示词
        print("📝 使用默认初始提示词")
        return self.meta_optimizer.get_initial_prompt()

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

