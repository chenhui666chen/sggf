"""
内容创作进化系统 - 反馈收集器

负责收集三个维度的隐式反馈信号：
1. 编辑量 (35%)：章节保存时统计修改比例
2. 保留率 (35%)：24小时后检查是否被删除
3. 重生次数 (30%)：实时记录重新生成次数
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import difflib

from .models import (
    GenerationRecord,
    ImplicitFeedback,
    FeedbackStatus,
)
from .storage import get_storage

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """隐式反馈收集器"""
    
    def __init__(self):
        self.storage = get_storage()
    
    # ==================== 编辑量信号 (35%) ====================
    
    def collect_edit_feedback(
        self,
        chapter_id: int,
        original_content: str,
        final_content: str
    ) -> Optional[float]:
        """
        收集编辑量反馈（章节保存时调用）
        
        Args:
            chapter_id: 章节ID
            original_content: 原始生成内容
            final_content: 用户保存的最终内容
            
        Returns:
            编辑比例 (0-1)，None表示未找到记录
        """
        record = self.storage.get_record_by_chapter(chapter_id)
        if not record:
            logger.warning(f"未找到章节 {chapter_id} 的生成记录")
            return None
        
        # 计算编辑量
        edit_ratio = self._calculate_edit_ratio(original_content, final_content)
        edit_distance = self._calculate_edit_distance(original_content, final_content)
        
        # 更新反馈
        feedback = record.implicit_feedback or ImplicitFeedback()
        feedback.original_length = len(original_content)
        feedback.final_length = len(final_content)
        feedback.edit_distance = edit_distance
        feedback.edit_ratio = edit_ratio
        feedback.status = FeedbackStatus.PARTIAL
        feedback.collected_at = datetime.now().isoformat()
        
        # 保存
        self.storage.update_record_feedback(record.record_id, feedback)
        
        logger.info(f"📝 收集编辑反馈: chapter={chapter_id}, edit_ratio={edit_ratio:.2%}")
        return edit_ratio
    
    def _calculate_edit_ratio(self, original: str, final: str) -> float:
        """
        计算编辑比例
        
        使用字符级别的相似度计算：
        edit_ratio = 1 - similarity
        """
        if not original:
            return 1.0 if final else 0.0
        
        # 使用 SequenceMatcher 计算相似度
        similarity = difflib.SequenceMatcher(None, original, final).ratio()
        return 1.0 - similarity
    
    def _calculate_edit_distance(self, original: str, final: str) -> int:
        """
        计算编辑距离（简化版，统计不同字符数）
        """
        if not original and not final:
            return 0
        if not original:
            return len(final)
        if not final:
            return len(original)
        
        # 统计差异操作数
        matcher = difflib.SequenceMatcher(None, original, final)
        distance = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'replace':
                distance += max(i2 - i1, j2 - j1)
            elif tag == 'delete':
                distance += i2 - i1
            elif tag == 'insert':
                distance += j2 - j1
        
        return distance
    
    # ==================== 保留率信号 (35%) ====================
    
    def collect_retention_feedback(
        self,
        chapter_id: int,
        is_deleted: bool
    ) -> bool:
        """
        收集保留率反馈（删除检查时调用）
        
        Args:
            chapter_id: 章节ID
            is_deleted: 是否被删除
            
        Returns:
            是否成功更新
        """
        record = self.storage.get_record_by_chapter(chapter_id)
        if not record:
            return False
        
        feedback = record.implicit_feedback or ImplicitFeedback()
        feedback.was_deleted = is_deleted
        feedback.check_time = datetime.now().isoformat()
        
        # 如果编辑量已收集，则标记为完成
        if feedback.edit_ratio > 0 or feedback.original_length > 0:
            feedback.status = FeedbackStatus.COMPLETE
        else:
            feedback.status = FeedbackStatus.PARTIAL
        
        self.storage.update_record_feedback(record.record_id, feedback)
        
        status = "已删除" if is_deleted else "保留"
        logger.info(f"📊 收集保留反馈: chapter={chapter_id}, status={status}")
        return True
    
    def check_pending_retentions(self, hours: int = 24) -> List[Tuple[int, bool]]:
        """
        检查待确认的保留率（24h后批量检查）
        
        Returns:
            [(chapter_id, needs_check), ...]
        """
        records = self.storage.get_records_pending_retention_check(hours)
        
        result = []
        for record in records:
            if record.chapter_id:
                result.append((record.chapter_id, True))
        
        if result:
            logger.info(f"📋 发现 {len(result)} 条待检查的保留率记录")
        
        return result
    
    # ==================== 重生次数信号 (30%) ====================
    
    def record_regeneration(self, chapter_id: int) -> int:
        """
        记录重新生成（重生成时调用）
        
        Args:
            chapter_id: 章节ID
            
        Returns:
            当前重生成次数
        """
        success = self.storage.increment_regenerate_count(chapter_id)
        
        if success:
            record = self.storage.get_record_by_chapter(chapter_id)
            if record and record.implicit_feedback:
                count = record.implicit_feedback.regenerate_count
                logger.info(f"🔄 记录重生成: chapter={chapter_id}, count={count}")
                return count
        
        return 0
    
    # ==================== 综合评分 ====================
    
    def get_chapter_score(self, chapter_id: int) -> Optional[float]:
        """
        获取章节的综合反馈评分
        
        Returns:
            评分 (0-100)，None表示未找到或数据不完整
        """
        record = self.storage.get_record_by_chapter(chapter_id)
        if not record or not record.implicit_feedback:
            return None
        
        return record.implicit_feedback.calculate_score()
    
    def get_variant_statistics(
        self,
        module_name: str,
        genre: str,
        variant_id: str = None,
        days: int = 7
    ) -> dict:
        """
        获取变体的统计数据
        
        Args:
            module_name: 模块名
            genre: 题材
            variant_id: 变体ID（None表示所有）
            days: 统计天数
            
        Returns:
            统计信息字典
        """
        records = self.storage.get_records_by_genre(genre, days=days)
        
        # 按变体分组
        variant_stats = {}
        for record in records:
            if record.prompt_module != module_name:
                continue
            if variant_id and record.prompt_version_id != variant_id:
                continue
            
            vid = record.prompt_version_id
            if vid not in variant_stats:
                variant_stats[vid] = {
                    "variant_id": vid,
                    "is_variant": record.is_variant,
                    "samples": [],
                    "scores": [],
                }
            
            if record.implicit_feedback:
                score = record.implicit_feedback.calculate_score()
                variant_stats[vid]["samples"].append(record.record_id)
                variant_stats[vid]["scores"].append(score)
        
        # 计算统计量
        result = {}
        for vid, data in variant_stats.items():
            scores = data["scores"]
            if scores:
                import statistics
                result[vid] = {
                    "variant_id": vid,
                    "is_variant": data["is_variant"],
                    "sample_count": len(scores),
                    "avg_score": statistics.mean(scores),
                    "std_score": statistics.stdev(scores) if len(scores) > 1 else 0,
                    "min_score": min(scores),
                    "max_score": max(scores),
                }
        
        return result


class RetentionChecker:
    """保留率检查器（定时任务）"""
    
    def __init__(self, db_session_factory=None):
        """
        初始化检查器
        
        Args:
            db_session_factory: 数据库会话工厂（用于查询章节是否存在）
        """
        self.db_session_factory = db_session_factory
        self.collector = FeedbackCollector()
    
    async def run_check(self) -> dict:
        """
        运行保留率检查
        
        Returns:
            检查结果统计
        """
        pending = self.collector.check_pending_retentions(hours=24)
        
        if not pending:
            return {"checked": 0, "retained": 0, "deleted": 0}
        
        retained = 0
        deleted = 0
        
        for chapter_id, _ in pending:
            exists = await self._check_chapter_exists(chapter_id)
            self.collector.collect_retention_feedback(chapter_id, is_deleted=not exists)
            
            if exists:
                retained += 1
            else:
                deleted += 1
        
        logger.info(f"✅ 保留率检查完成: 保留={retained}, 删除={deleted}")
        return {
            "checked": len(pending),
            "retained": retained,
            "deleted": deleted,
        }
    
    async def _check_chapter_exists(self, chapter_id: int) -> bool:
        """检查章节是否仍存在于数据库"""
        if not self.db_session_factory:
            # 没有数据库连接，默认认为存在
            return True
        
        try:
            from app.models.novel import Chapter
            
            async with self.db_session_factory() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Chapter.id).where(Chapter.id == chapter_id)
                )
                return result.scalar() is not None
        except Exception as e:
            logger.error(f"检查章节存在性失败: {e}")
            return True  # 出错时默认存在，避免误判


class ScoreAggregator:
    """评分聚合器 - 计算变体的综合表现"""
    
    def __init__(self):
        self.storage = get_storage()
        self.collector = FeedbackCollector()
    
    def should_evolve(
        self,
        module_name: str,
        genre: str,
        min_samples: int = 50
    ) -> Tuple[bool, str]:
        """
        判断是否应该触发进化
        
        Args:
            module_name: 模块名
            genre: 题材
            min_samples: 最少样本数
            
        Returns:
            (should_evolve, reason)
        """
        # 获取变体统计
        stats = self.collector.get_variant_statistics(module_name, genre)
        
        # 分离最佳版本和测试变体
        best_stats = None
        variant_stats = None
        
        for vid, data in stats.items():
            if data.get("is_variant"):
                variant_stats = data
            else:
                best_stats = data
        
        if not variant_stats:
            return False, "没有正在测试的变体"
        
        if variant_stats["sample_count"] < min_samples:
            return False, f"样本不足: {variant_stats['sample_count']}/{min_samples}"
        
        # 检查标准差是否够小（结果稳定）
        if variant_stats["std_score"] > 15:
            return False, f"结果不稳定: std={variant_stats['std_score']:.1f}"
        
        # 对比效果
        if not best_stats:
            return True, "promote_variant"  # 没有最佳版本，直接提升
        
        diff = variant_stats["avg_score"] - best_stats["avg_score"]
        
        if diff > 5:
            return True, f"variant_better: +{diff:.1f}分"
        elif diff < -10:
            return True, f"variant_worse: {diff:.1f}分"
        else:
            return False, f"差异不显著: {diff:+.1f}分"
    
    def get_evolution_decision(
        self,
        module_name: str,
        genre: str
    ) -> dict:
        """
        获取进化决策
        
        Returns:
            {
                "action": "promote" | "discard" | "continue",
                "reason": str,
                "variant_stats": dict,
                "best_stats": dict
            }
        """
        should, reason = self.should_evolve(module_name, genre)
        
        stats = self.collector.get_variant_statistics(module_name, genre)
        
        # 分离统计
        best_stats = None
        variant_stats = None
        for vid, data in stats.items():
            if data.get("is_variant"):
                variant_stats = data
            else:
                best_stats = data
        
        if not should:
            action = "continue"
        elif "better" in reason:
            action = "promote"
        elif "worse" in reason:
            action = "discard"
        else:
            action = "promote"  # 默认提升
        
        return {
            "action": action,
            "reason": reason,
            "variant_stats": variant_stats,
            "best_stats": best_stats,
        }


# 全局实例
_collector_instance: Optional[FeedbackCollector] = None


def get_collector() -> FeedbackCollector:
    """获取收集器实例（单例）"""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = FeedbackCollector()
    return _collector_instance
