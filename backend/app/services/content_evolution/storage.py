"""
内容创作进化系统 - 存储管理
使用JSON文件存储生成记录、变体和进化历史
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging

from .models import (
    GenerationRecord, 
    PromptVariant, 
    EvolutionSession,
    FeedbackStatus,
    ImplicitFeedback
)

logger = logging.getLogger(__name__)


class ContentEvolutionStorage:
    """内容进化存储管理器"""
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        初始化存储管理器
        
        Args:
            storage_dir: 存储目录路径，默认为 data/content_evolution/
        """
        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "content_evolution")
        
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件路径
        self.records_file = self.storage_dir / "generation_records.json"
        self.variants_file = self.storage_dir / "prompt_variants.json"
        self.sessions_file = self.storage_dir / "evolution_sessions.json"
        self.best_prompts_dir = self.storage_dir / "best_prompts"
        self.best_prompts_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📁 内容进化存储目录初始化: {self.storage_dir}")
    
    # ==================== 生成记录管理 ====================
    
    def save_generation_record(self, record: GenerationRecord) -> None:
        """保存生成记录"""
        records = self._load_all_records()
        
        # 更新或添加
        record_dict = record.to_dict()
        found = False
        for i, r in enumerate(records):
            if r.get("record_id") == record.record_id:
                records[i] = record_dict
                found = True
                break
        if not found:
            records.append(record_dict)
        
        self._save_records(records)
        logger.debug(f"💾 保存生成记录: {record.record_id}")
    
    def get_record_by_chapter(self, chapter_id: int) -> Optional[GenerationRecord]:
        """根据章节ID获取最新的生成记录"""
        records = self._load_all_records()
        # 按时间倒序找最新的
        chapter_records = [r for r in records if r.get("chapter_id") == chapter_id]
        if not chapter_records:
            return None
        # 取最新的
        latest = max(chapter_records, key=lambda x: x.get("generated_at", ""))
        return GenerationRecord.from_dict(latest)
    
    def get_records_by_genre(
        self, 
        genre: str, 
        days: int = 7,
        is_variant: Optional[bool] = None
    ) -> List[GenerationRecord]:
        """获取指定题材的生成记录"""
        records = self._load_all_records()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        result = []
        for r in records:
            if r.get("genre") != genre:
                continue
            if r.get("generated_at", "") < cutoff:
                continue
            if is_variant is not None and r.get("is_variant") != is_variant:
                continue
            result.append(GenerationRecord.from_dict(r))
        
        return result
    
    def get_records_pending_retention_check(self, hours: int = 24) -> List[GenerationRecord]:
        """获取需要进行保留率检查的记录（生成超过24h且未检查）"""
        records = self._load_all_records()
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        result = []
        for r in records:
            # 生成时间超过24h
            if r.get("generated_at", "") > cutoff:
                continue
            # 有反馈数据但未完成保留率检查
            feedback = r.get("implicit_feedback")
            if feedback and feedback.get("check_time") is None:
                result.append(GenerationRecord.from_dict(r))
        
        return result
    
    def update_record_feedback(
        self, 
        record_id: str, 
        feedback: ImplicitFeedback
    ) -> bool:
        """更新记录的反馈数据"""
        records = self._load_all_records()
        
        for i, r in enumerate(records):
            if r.get("record_id") == record_id:
                records[i]["implicit_feedback"] = feedback.to_dict()
                self._save_records(records)
                logger.info(f"📊 更新反馈数据: {record_id}")
                return True
        
        return False
    
    def increment_regenerate_count(self, chapter_id: int) -> bool:
        """增加章节的重生成次数"""
        records = self._load_all_records()
        
        # 找到该章节最新的记录
        chapter_records = [(i, r) for i, r in enumerate(records) 
                          if r.get("chapter_id") == chapter_id]
        if not chapter_records:
            return False
        
        # 取最新的
        idx, latest = max(chapter_records, key=lambda x: x[1].get("generated_at", ""))
        
        # 更新重生成次数
        feedback = latest.get("implicit_feedback") or {}
        feedback["regenerate_count"] = feedback.get("regenerate_count", 0) + 1
        feedback["status"] = FeedbackStatus.PARTIAL.value
        records[idx]["implicit_feedback"] = feedback
        
        self._save_records(records)
        logger.info(f"🔄 章节 {chapter_id} 重生成次数+1")
        return True
    
    def _load_all_records(self) -> List[Dict]:
        """加载所有生成记录"""
        if not self.records_file.exists():
            return []
        try:
            with open(self.records_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载生成记录失败: {e}")
            return []
    
    def _save_records(self, records: List[Dict]) -> None:
        """保存生成记录"""
        with open(self.records_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    
    # ==================== 提示词变体管理 ====================
    
    def save_variant(self, variant: PromptVariant) -> None:
        """保存提示词变体"""
        variants = self._load_all_variants()
        
        variant_dict = variant.to_dict()
        found = False
        for i, v in enumerate(variants):
            if v.get("variant_id") == variant.variant_id:
                variants[i] = variant_dict
                found = True
                break
        if not found:
            variants.append(variant_dict)
        
        self._save_variants(variants)
        logger.debug(f"💾 保存变体: {variant.variant_id}")
    
    def get_current_best(self, module_name: str, genre: str) -> Optional[PromptVariant]:
        """获取指定模块和题材的当前最佳变体"""
        variants = self._load_all_variants()
        
        for v in variants:
            if (v.get("module_name") == module_name and 
                v.get("genre") == genre and 
                v.get("is_current_best") == True):
                return PromptVariant.from_dict(v)
        
        return None
    
    def get_active_variant(self, module_name: str, genre: str) -> Optional[PromptVariant]:
        """获取当前激活的测试变体"""
        variants = self._load_all_variants()
        
        for v in variants:
            if (v.get("module_name") == module_name and 
                v.get("genre") == genre and 
                v.get("is_active") == True and
                v.get("is_current_best") == False):
                return PromptVariant.from_dict(v)
        
        return None
    
    def get_variants_by_module(
        self, 
        module_name: str, 
        genre: str
    ) -> List[PromptVariant]:
        """获取指定模块的所有变体"""
        variants = self._load_all_variants()
        
        result = []
        for v in variants:
            if v.get("module_name") == module_name and v.get("genre") == genre:
                result.append(PromptVariant.from_dict(v))
        
        return result
    
    def update_variant_stats(
        self, 
        variant_id: str, 
        score: float
    ) -> bool:
        """更新变体的统计数据"""
        variants = self._load_all_variants()
        
        for i, v in enumerate(variants):
            if v.get("variant_id") == variant_id:
                # 增量更新平均分
                old_count = v.get("sample_count", 0)
                old_avg = v.get("avg_score", 0.0)
                new_count = old_count + 1
                new_avg = (old_avg * old_count + score) / new_count
                
                variants[i]["sample_count"] = new_count
                variants[i]["avg_score"] = new_avg
                variants[i]["last_evaluated_at"] = datetime.now().isoformat()
                
                self._save_variants(variants)
                logger.info(f"📈 更新变体统计: {variant_id}, 样本数={new_count}, 平均分={new_avg:.2f}")
                return True
        
        return False
    
    def promote_variant_to_best(self, variant_id: str) -> bool:
        """将变体提升为当前最佳"""
        variants = self._load_all_variants()
        
        # 找到目标变体
        target_idx = None
        target_module = None
        target_genre = None
        for i, v in enumerate(variants):
            if v.get("variant_id") == variant_id:
                target_idx = i
                target_module = v.get("module_name")
                target_genre = v.get("genre")
                break
        
        if target_idx is None:
            return False
        
        # 取消原来的最佳标记
        for i, v in enumerate(variants):
            if (v.get("module_name") == target_module and 
                v.get("genre") == target_genre and
                v.get("is_current_best") == True):
                variants[i]["is_current_best"] = False
        
        # 设置新的最佳
        variants[target_idx]["is_current_best"] = True
        variants[target_idx]["is_active"] = False  # 不再作为测试变体
        
        self._save_variants(variants)
        logger.info(f"🏆 变体 {variant_id} 提升为最佳")
        return True
    
    def _load_all_variants(self) -> List[Dict]:
        """加载所有变体"""
        if not self.variants_file.exists():
            return []
        try:
            with open(self.variants_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载变体失败: {e}")
            return []
    
    def _save_variants(self, variants: List[Dict]) -> None:
        """保存变体"""
        with open(self.variants_file, "w", encoding="utf-8") as f:
            json.dump(variants, f, ensure_ascii=False, indent=2)
    
    # ==================== 进化会话管理 ====================
    
    def save_session(self, session: EvolutionSession) -> None:
        """保存进化会话"""
        sessions = self._load_all_sessions()
        
        session_dict = session.to_dict()
        found = False
        for i, s in enumerate(sessions):
            if s.get("session_id") == session.session_id:
                sessions[i] = session_dict
                found = True
                break
        if not found:
            sessions.append(session_dict)
        
        self._save_sessions(sessions)
        logger.debug(f"💾 保存会话: {session.session_id}")
    
    def get_session(self, module_name: str, genre: str) -> Optional[EvolutionSession]:
        """获取指定模块和题材的进化会话"""
        sessions = self._load_all_sessions()
        
        for s in sessions:
            if s.get("module_name") == module_name and s.get("genre") == genre:
                return EvolutionSession.from_dict(s)
        
        return None
    
    def get_or_create_session(
        self, 
        module_name: str, 
        genre: str
    ) -> EvolutionSession:
        """获取或创建进化会话"""
        session = self.get_session(module_name, genre)
        if session is None:
            session = EvolutionSession(
                module_name=module_name,
                genre=genre
            )
            self.save_session(session)
            logger.info(f"🆕 创建新会话: {module_name}/{genre}")
        return session
    
    def _load_all_sessions(self) -> List[Dict]:
        """加载所有会话"""
        if not self.sessions_file.exists():
            return []
        try:
            with open(self.sessions_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载会话失败: {e}")
            return []
    
    def _save_sessions(self, sessions: List[Dict]) -> None:
        """保存会话"""
        with open(self.sessions_file, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    
    # ==================== 最佳提示词管理 ====================
    
    def save_best_prompt(
        self, 
        module_name: str, 
        genre: str, 
        prompt_text: str,
        metadata: Dict[str, Any] = None
    ) -> None:
        """保存最佳提示词到文件"""
        filename = f"{module_name}_{genre}.json"
        filepath = self.best_prompts_dir / filename
        
        data = {
            "module_name": module_name,
            "genre": genre,
            "prompt_text": prompt_text,
            "metadata": metadata or {},
            "updated_at": datetime.now().isoformat()
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 保存最佳提示词: {filename}")
    
    def load_best_prompt(self, module_name: str, genre: str) -> Optional[str]:
        """加载最佳提示词"""
        filename = f"{module_name}_{genre}.json"
        filepath = self.best_prompts_dir / filename
        
        if not filepath.exists():
            return None
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("prompt_text")
        except Exception as e:
            logger.error(f"加载最佳提示词失败: {e}")
            return None
    
    # ==================== 数据清理 ====================
    
    def cleanup_old_records(self, keep_days: int = 30) -> int:
        """清理旧的生成记录"""
        records = self._load_all_records()
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
        
        # 保留最近的记录
        new_records = [r for r in records if r.get("generated_at", "") >= cutoff]
        deleted = len(records) - len(new_records)
        
        if deleted > 0:
            self._save_records(new_records)
            logger.info(f"🧹 清理旧记录: 删除 {deleted} 条")
        
        return deleted
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        records = self._load_all_records()
        variants = self._load_all_variants()
        sessions = self._load_all_sessions()
        
        # 按题材统计
        genre_stats = {}
        for r in records:
            genre = r.get("genre", "通用")
            if genre not in genre_stats:
                genre_stats[genre] = {"total": 0, "variant": 0}
            genre_stats[genre]["total"] += 1
            if r.get("is_variant"):
                genre_stats[genre]["variant"] += 1
        
        return {
            "total_records": len(records),
            "total_variants": len(variants),
            "total_sessions": len(sessions),
            "genre_stats": genre_stats,
            "storage_dir": str(self.storage_dir)
        }


# 全局实例
_storage_instance: Optional[ContentEvolutionStorage] = None


def get_storage() -> ContentEvolutionStorage:
    """获取存储实例（单例）"""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = ContentEvolutionStorage()
    return _storage_instance
