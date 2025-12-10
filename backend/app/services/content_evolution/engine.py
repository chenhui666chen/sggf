"""
内容创作进化引擎

核心进化逻辑：
1. 基于隐式反馈（编辑量35%+保留率35%+重生次数30%）评估效果
2. 5%低频采样测试变体
3. AI随机探索变体方向
4. 自动提升/丢弃变体决策
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Awaitable, List

from .models import (
    GenerationRecord,
    PromptVariant,
    EvolutionSession,
    ContentEvolutionConfig,
    GenerationStage,
)
from .storage import get_storage, ContentEvolutionStorage
from .variant_router import VariantRouter, VariantGenerator, get_router
from .feedback_collector import (
    FeedbackCollector,
    ScoreAggregator,
    RetentionChecker,
    get_collector,
)
from .genre_weights import get_genre_profile, build_evaluation_prompt
from .experience_optimizer import get_content_experience_optimizer, ExperienceItem

logger = logging.getLogger(__name__)


class ContentEvolutionEngine:
    """内容创作进化引擎"""
    
    def __init__(
        self,
        config: ContentEvolutionConfig = None,
        llm_caller: Callable[[str, float], Awaitable[str]] = None,
        db_session_factory = None,
    ):
        """
        初始化进化引擎
        
        Args:
            config: 进化配置
            llm_caller: LLM调用函数，签名为 async (prompt, temperature) -> str
            db_session_factory: 数据库会话工厂（用于保留率检查）
        """
        self.config = config or ContentEvolutionConfig()
        self.storage = get_storage()
        self.router = get_router()
        self.collector = get_collector()
        self.aggregator = ScoreAggregator()
        self.variant_generator = VariantGenerator(llm_caller)
        self.retention_checker = RetentionChecker(db_session_factory)
        self.llm_caller = llm_caller
        
        logger.info("🚀 内容进化引擎初始化完成")
    
    # ==================== 生成时调用 ====================
    
    async def on_generation_start(
        self,
        project_id: int,
        chapter_id: Optional[int],
        genre: str,
        stage: GenerationStage,
        module_name: str,
        default_prompt: str,
        chapter_number: int = 0,
    ) -> tuple:
        """
        生成开始时调用 - 决定使用哪个提示词
        
        Returns:
            (prompt_to_use, version_id, is_variant)
        """
        prompt, version_id, is_variant = self.router.get_prompt_for_generation(
            module_name=module_name,
            genre=genre,
            project_id=project_id,
            chapter_number=chapter_number,
            default_prompt=default_prompt,
        )
        
        if is_variant:
            logger.info(f"🧪 使用变体提示词: {version_id}")
        
        return prompt, version_id, is_variant
    
    async def on_generation_complete(
        self,
        project_id: int,
        chapter_id: Optional[int],
        genre: str,
        stage: GenerationStage,
        module_name: str,
        version_id: str,
        is_variant: bool,
        content: str,
        ai_score: Optional[Dict[str, float]] = None,
    ) -> GenerationRecord:
        """
        生成完成时调用 - 记录生成数据
        
        Args:
            project_id: 项目ID
            chapter_id: 章节ID
            genre: 题材
            stage: 阶段
            module_name: 模块名
            version_id: 提示词版本ID
            is_variant: 是否变体
            content: 生成内容
            ai_score: AI评分（如果有）
            
        Returns:
            生成记录
        """
        record = self.router.record_generation(
            project_id=project_id,
            chapter_id=chapter_id,
            genre=genre,
            stage=stage,
            prompt_version_id=version_id,
            prompt_module=module_name,
            is_variant=is_variant,
            content=content,
            ai_score=ai_score,
        )
        
        logger.info(f"📊 记录生成: record={record.record_id}, variant={is_variant}")
        return record
    
    # ==================== 反馈收集 ====================
    
    async def on_chapter_save(
        self,
        chapter_id: int,
        original_content: str,
        final_content: str,
    ) -> Optional[float]:
        """
        章节保存时调用 - 收集编辑量反馈
        
        Returns:
            编辑比例 (0-1)
        """
        edit_ratio = self.collector.collect_edit_feedback(
            chapter_id=chapter_id,
            original_content=original_content,
            final_content=final_content,
        )
        
        if edit_ratio is not None:
            logger.info(f"📝 编辑反馈: chapter={chapter_id}, ratio={edit_ratio:.2%}")
            
            # 检查是否需要触发进化
            await self._check_evolution_trigger(chapter_id)
        
        return edit_ratio
    
    async def on_chapter_regenerate(self, chapter_id: int) -> int:
        """
        章节重生成时调用 - 记录重生成次数
        
        Returns:
            当前重生成次数
        """
        count = self.collector.record_regeneration(chapter_id)
        logger.info(f"🔄 重生成: chapter={chapter_id}, count={count}")
        return count
    
    async def on_chapter_delete(self, chapter_id: int) -> bool:
        """
        章节删除时调用 - 收集保留率反馈
        """
        success = self.collector.collect_retention_feedback(
            chapter_id=chapter_id,
            is_deleted=True,
        )
        if success:
            logger.info(f"🗑️ 删除反馈: chapter={chapter_id}")
        return success
    
    # ==================== 进化触发 ====================
    
    async def _check_evolution_trigger(self, chapter_id: int) -> None:
        """检查是否需要触发进化"""
        record = self.storage.get_record_by_chapter(chapter_id)
        if not record:
            return
        
        if not record.is_variant:
            return  # 非变体记录不触发进化检查
        
        # 获取会话
        session = self.storage.get_session(record.prompt_module, record.genre)
        if not session:
            return
        
        # 检查样本数是否足够
        if session.total_samples < self.config.min_samples_for_evolution:
            logger.debug(f"样本不足: {session.total_samples}/{self.config.min_samples_for_evolution}")
            return
        
        # 执行进化决策
        await self.run_evolution_check(record.prompt_module, record.genre)
    
    async def run_evolution_check(
        self,
        module_name: str,
        genre: str,
    ) -> Dict[str, Any]:
        """
        运行进化检查
        
        Returns:
            进化决策结果
        """
        decision = self.aggregator.get_evolution_decision(module_name, genre)
        
        action = decision["action"]
        reason = decision["reason"]
        
        logger.info(f"🧬 进化决策: {module_name}/{genre} -> {action} ({reason})")
        
        if action == "promote":
            # 提升变体为新的最佳
            await self._promote_variant(module_name, genre, decision)
        elif action == "discard":
            # 丢弃变体，生成新的
            await self._discard_and_generate_new(module_name, genre, decision)
        # else: continue - 继续观察
        
        return decision
    
    async def _promote_variant(
        self,
        module_name: str,
        genre: str,
        decision: Dict[str, Any],
    ) -> None:
        """提升变体为最佳"""
        variant_stats = decision.get("variant_stats")
        if not variant_stats:
            return
        
        variant_id = variant_stats["variant_id"]
        
        # 提升变体
        success = self.storage.promote_variant_to_best(variant_id)
        if success:
            # 更新会话
            session = self.storage.get_or_create_session(module_name, genre)
            session.current_best_id = variant_id
            session.variants_tested += 1
            session.last_evolution_at = datetime.now().isoformat()
            
            # 计算改善率
            best_stats = decision.get("best_stats")
            if best_stats:
                old_score = best_stats.get("avg_score", 0)
                new_score = variant_stats.get("avg_score", 0)
                if old_score > 0:
                    session.improvement_rate = (new_score - old_score) / old_score * 100
            
            self.storage.save_session(session)
            
            # 保存最佳提示词到文件
            variant = self.storage.get_current_best(module_name, genre)
            if variant:
                self.storage.save_best_prompt(
                    module_name, genre, variant.prompt_text,
                    metadata={
                        "variant_id": variant_id,
                        "avg_score": variant_stats.get("avg_score"),
                        "sample_count": variant_stats.get("sample_count"),
                    }
                )
            
            logger.info(f"🏆 变体提升成功: {variant_id}")
            
            # 生成新的测试变体
            await self._generate_new_variant(module_name, genre)
    
    async def _discard_and_generate_new(
        self,
        module_name: str,
        genre: str,
        decision: Dict[str, Any],
    ) -> None:
        """丢弃当前变体，生成新的"""
        variant_stats = decision.get("variant_stats")
        if variant_stats:
            variant_id = variant_stats["variant_id"]
            
            # 标记为不活跃
            variants = self.storage._load_all_variants()
            for i, v in enumerate(variants):
                if v.get("variant_id") == variant_id:
                    variants[i]["is_active"] = False
                    break
            self.storage._save_variants(variants)
            
            logger.info(f"❌ 变体丢弃: {variant_id}")
        
        # 生成新的测试变体
        await self._generate_new_variant(module_name, genre)
    
    async def _generate_new_variant(
        self,
        module_name: str,
        genre: str,
    ) -> Optional[PromptVariant]:
        """生成新的测试变体"""
        if not self.llm_caller:
            logger.warning("未配置LLM，无法生成变体")
            return None
        
        # 获取当前最佳提示词
        current_best = self.storage.get_current_best(module_name, genre)
        if not current_best:
            logger.warning(f"没有最佳版本: {module_name}/{genre}")
            return None
        
        # 获取最近的评分数据
        records = self.storage.get_records_by_genre(genre, days=7)
        recent_scores = [
            r.implicit_feedback.calculate_score()
            for r in records
            if r.implicit_feedback and r.prompt_module == module_name
        ]
        
        # 使用AI生成新变体
        new_variant = await self.variant_generator.generate_variant(
            current_prompt=current_best.prompt_text,
            module_name=module_name,
            genre=genre,
            recent_scores=recent_scores,
        )
        
        if new_variant:
            logger.info(f"🆕 新变体生成: {new_variant.variant_id}")
        
        return new_variant
    
    # ==================== 定时任务 ====================
    
    async def run_retention_check(self) -> Dict[str, int]:
        """
        运行保留率检查（定时任务，建议每小时运行）
        
        Returns:
            检查结果统计
        """
        result = await self.retention_checker.run_check()
        logger.info(f"✅ 保留率检查: {result}")
        return result
    
    async def run_scheduled_evolution(self) -> Dict[str, Any]:
        """
        运行计划进化（定时任务，建议每天运行）
        
        遍历所有活跃会话，检查是否需要进化
        """
        sessions = self.storage._load_all_sessions()
        results = {}
        
        for s in sessions:
            if s.get("status") != "running":
                continue
            
            module_name = s.get("module_name")
            genre = s.get("genre")
            
            try:
                decision = await self.run_evolution_check(module_name, genre)
                results[f"{module_name}/{genre}"] = decision
            except Exception as e:
                logger.error(f"进化检查失败: {module_name}/{genre}: {e}")
                results[f"{module_name}/{genre}"] = {"error": str(e)}
        
        logger.info(f"📊 计划进化完成: {len(results)} 个会话")
        return results
    
    # ==================== 🆕 经验库优化 ====================
    
    async def run_experience_optimization(
        self,
        module_name: str,
        genre: str
    ) -> Dict[str, Any]:
        """
        🆕 运行经验库优化
        
        在进化开始前自动触发，去重、合并、过滤历史经验
        
        Args:
            module_name: 模块名称 (chapter/outline/character)
            genre: 题材
        
        Returns:
            优化结果
        """
        logger.info(f"🆕 开始经验库优化: {module_name}/{genre}")
        
        optimizer = get_content_experience_optimizer()
        
        # 检查是否需要优化
        total_variants = len(self.storage.get_variants_by_module(module_name, genre))
        last_count = self.storage.get_last_optimization_count(module_name, genre)
        
        should_optimize = optimizer.should_trigger_optimization(total_variants, last_count)
        
        if not should_optimize:
            logger.info(f"⛔ 经验库不需要优化: 变体数={total_variants}, 上次={last_count}")
            return {
                "optimized": False,
                "reason": "未达到触发条件",
                "total_variants": total_variants,
                "last_count": last_count
            }
        
        # 收集经验数据（从变体记录中提取）
        experiences = await self._collect_experiences_from_variants(module_name, genre)
        
        if not experiences or sum(len(items) for items in experiences.values()) == 0:
            logger.warning(f"⚠️ 没有找到可优化的经验")
            return {
                "optimized": False,
                "reason": "没有经验数据"
            }
        
        # 执行优化
        top_experiences, summary = await optimizer.optimize_experiences(
            experiences,
            module_name=module_name,
            genre=genre
        )
        
        # 保存优化结果
        self.storage.save_optimization_metadata(
            module_name,
            genre,
            top_experiences,
            summary
        )
        
        logger.info(f"✅ 经验库优化完成: 保留{len(top_experiences)}条核心经验")
        logger.info(f"\n{summary}")
        
        return {
            "optimized": True,
            "total_experiences": len(top_experiences),
            "summary": summary
        }
    
    async def _collect_experiences_from_variants(
        self,
        module_name: str,
        genre: str
    ) -> Dict[str, List[ExperienceItem]]:
        """
        从变体记录中收集经验
        
        Returns:
            {
                "variant_success": [ExperienceItem, ...],
                "variant_failure": [ExperienceItem, ...],
                "feedback_patterns": [ExperienceItem, ...]
            }
        """
        experiences = {
            "variant_success": [],
            "variant_failure": [],
            "feedback_patterns": []
        }
        
        # 获取所有变体
        variants = self.storage.get_variants_by_module(module_name, genre)
        
        for variant in variants:
            # 根据平均分判断成功/失败
            if variant.sample_count < 3:
                continue  # 样本太少，跳过
            
            category = "variant_success" if variant.avg_score >= 60 else "variant_failure"
            
            experience = ExperienceItem(
                text=variant.mutation_description or f"变体{variant.variant_id}的优化策略",
                category=category,
                appearance_count=variant.sample_count,
                source_reports=[variant.variant_id],
                first_seen=variant.created_at,
                last_seen=variant.last_evaluated_at or variant.created_at,
                avg_score_improvement=variant.avg_score - 50,  # 基准50分计算提升
                success_rate=variant.avg_score / 100  # 转换为0-1
            )
            
            experiences[category].append(experience)
        
        # 收集反馈规律（从生成记录中提取高频反馈模式）
        records = self.storage.get_records_by_genre(genre, days=30)
        feedback_patterns = self._extract_feedback_patterns(records)
        experiences["feedback_patterns"].extend(feedback_patterns)
        
        return experiences
    
    def _extract_feedback_patterns(self, records: List) -> List[ExperienceItem]:
        """
        从记录中提取反馈规律
        
        例如：
        - 编辑量高的共同特征
        - 重生成多的共同特征
        - 保留率高的共同特征
        """
        # 简化实现：返回空列表
        # TODO: 实现更复杂的规律提取逻辑
        return []
    
    # ==================== 手动操作 ====================
    
    async def initialize_module(
        self,
        module_name: str,
        genre: str,
        initial_prompt: str,
    ) -> PromptVariant:
        """
        初始化模块的提示词（首次使用时调用）
        
        Args:
            module_name: 模块名
            genre: 题材
            initial_prompt: 初始提示词
            
        Returns:
            创建的变体
        """
        # 检查是否已有最佳版本
        existing = self.storage.get_current_best(module_name, genre)
        if existing:
            logger.info(f"模块已初始化: {module_name}/{genre}")
            return existing
        
        # 创建初始版本
        variant = PromptVariant(
            module_name=module_name,
            genre=genre,
            prompt_text=initial_prompt,
            mutation_description="初始版本",
            is_current_best=True,
            is_active=False,  # 最佳版本不作为测试变体
        )
        
        self.storage.save_variant(variant)
        
        # 创建会话
        session = self.storage.get_or_create_session(module_name, genre)
        session.current_best_id = variant.variant_id
        self.storage.save_session(session)
        
        # 保存最佳提示词
        self.storage.save_best_prompt(module_name, genre, initial_prompt)
        
        logger.info(f"✅ 模块初始化: {module_name}/{genre}")
        return variant
    
    async def force_generate_variant(
        self,
        module_name: str,
        genre: str,
    ) -> Optional[PromptVariant]:
        """
        强制生成新变体（手动触发）
        """
        return await self._generate_new_variant(module_name, genre)
    
    async def get_module_status(
        self,
        module_name: str,
        genre: str,
    ) -> Dict[str, Any]:
        """
        获取模块状态
        """
        session = self.storage.get_session(module_name, genre)
        current_best = self.storage.get_current_best(module_name, genre)
        active_variant = self.storage.get_active_variant(module_name, genre)
        stats = self.collector.get_variant_statistics(module_name, genre)
        
        return {
            "module_name": module_name,
            "genre": genre,
            "session": session.to_dict() if session else None,
            "current_best": current_best.to_dict() if current_best else None,
            "active_variant": active_variant.to_dict() if active_variant else None,
            "statistics": stats,
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取整体统计"""
        return self.storage.get_statistics()


# ==================== 便捷函数 ====================

_engine_instance: Optional[ContentEvolutionEngine] = None


def get_engine(
    llm_caller: Callable = None,
    db_session_factory = None,
) -> ContentEvolutionEngine:
    """
    获取进化引擎实例（单例）
    
    Args:
        llm_caller: LLM调用函数
        db_session_factory: 数据库会话工厂
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ContentEvolutionEngine(
            llm_caller=llm_caller,
            db_session_factory=db_session_factory,
        )
    return _engine_instance


async def quick_evaluate(
    content: str,
    genre: str,
    llm_caller: Callable[[str, float], Awaitable[str]],
    context: Dict[str, Any] = None,
) -> Dict[str, float]:
    """
    快速评估内容质量（独立使用）
    
    Args:
        content: 待评估内容
        genre: 题材
        llm_caller: LLM调用函数
        context: 上下文
        
    Returns:
        各维度评分
    """
    import json
    
    prompt = build_evaluation_prompt(genre, content, context)
    
    try:
        result = await llm_caller(prompt, 0.1)
        
        # 尝试解析JSON
        import re
        json_match = re.search(r'\{[^{}]+\}', result, re.DOTALL)
        if json_match:
            scores = json.loads(json_match.group())
            return scores
    except Exception as e:
        logger.error(f"评估失败: {e}")
    
    return {}
