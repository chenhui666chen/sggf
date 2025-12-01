"""
提示词进化系统 - 存储管理
使用JSON文件存储优化历史和最佳提示词
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging

from .models import PromptVersion, EvolutionHistory, ApprovalStatus

logger = logging.getLogger(__name__)


class EvolutionStorage:
    """进化历史存储管理器"""
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        初始化存储管理器
        
        Args:
            storage_dir: 存储目录路径，默认为 data/prompt_evolution/
        """
        if storage_dir is None:
            # 默认存储在项目根目录的 data/prompt_evolution/ 下
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution")
        
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件路径
        self.history_file = self.storage_dir / "evolution_history.json"
        self.best_prompts_file = self.storage_dir / "best_prompts.json"
        self.approved_prompts_file = self.storage_dir / "approved_prompts.json"
        self.experience_dir = self.storage_dir / "experience_reports"
        self.experience_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📁 存储目录初始化: {self.storage_dir}")
    
    def save_evolution_history(self, history: EvolutionHistory) -> None:
        """保存进化历史"""
        # 读取现有历史
        all_histories = self._load_all_histories()
        
        # 更新或添加
        history_dict = self._history_to_dict(history)
        found = False
        for i, h in enumerate(all_histories):
            if h.get("evolution_id") == history.evolution_id:
                all_histories[i] = history_dict
                found = True
                break
        if not found:
            all_histories.append(history_dict)
        
        # 保存
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(all_histories, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 保存进化历史: {history.evolution_id}")
    
    def load_evolution_history(self, evolution_id: str) -> Optional[EvolutionHistory]:
        """加载指定的进化历史"""
        all_histories = self._load_all_histories()
        for h in all_histories:
            if h.get("evolution_id") == evolution_id:
                return self._dict_to_history(h)
        return None
    
    def list_evolution_histories(self) -> List[Dict[str, Any]]:
        """列出所有进化历史（摘要）"""
        all_histories = self._load_all_histories()
        return [
            {
                "evolution_id": h.get("evolution_id"),
                "status": h.get("status"),
                "target_score": h.get("target_score"),
                "current_iteration": h.get("current_iteration"),
                "best_score": h.get("best_versions", [{}])[0].get("avg_ai_score") if h.get("best_versions") else None,
                "approval_status": h.get("approval_status"),
                "started_at": h.get("started_at"),
                "completed_at": h.get("completed_at")
            }
            for h in all_histories
        ]

    def delete_evolution_history(self, evolution_id: str) -> bool:
        """删除指定的进化历史"""
        all_histories = self._load_all_histories()
        original_count = len(all_histories)

        # 过滤掉要删除的历史
        all_histories = [h for h in all_histories if h.get("evolution_id") != evolution_id]

        if len(all_histories) == original_count:
            return False  # 没找到

        # 保存
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(all_histories, f, ensure_ascii=False, indent=2)

        # 同时删除经验报告
        experience_file = self.experience_dir / f"{evolution_id}.json"
        if experience_file.exists():
            experience_file.unlink()

        logger.info(f"🗑️ 删除进化历史: {evolution_id}")
        return True

    def cleanup_histories(self, keep_recent: int = 10, keep_best: int = 5) -> int:
        """
        自动清理历史记录

        保留规则：
        1. 保留最近 keep_recent 个历史
        2. 保留得分最好（最低）的 keep_best 个历史
        3. 保留已批准的历史
        4. 保留正在运行的历史

        Returns:
            删除的历史数量
        """
        all_histories = self._load_all_histories()
        if len(all_histories) <= keep_recent:
            return 0  # 数量不多，不需要清理

        # 标记需要保留的历史
        keep_ids = set()

        # 1. 保留正在运行和已批准的
        for h in all_histories:
            if h.get("status") == "running" or h.get("approval_status") == "approved":
                keep_ids.add(h.get("evolution_id"))

        # 2. 按时间排序，保留最近的
        sorted_by_time = sorted(
            all_histories,
            key=lambda x: x.get("started_at", ""),
            reverse=True
        )
        for h in sorted_by_time[:keep_recent]:
            keep_ids.add(h.get("evolution_id"))

        # 3. 按得分排序，保留最好的（得分最低）
        histories_with_score = [h for h in all_histories if h.get("best_versions")]
        sorted_by_score = sorted(
            histories_with_score,
            key=lambda x: x.get("best_versions", [{}])[0].get("avg_ai_score", 100)
        )
        for h in sorted_by_score[:keep_best]:
            keep_ids.add(h.get("evolution_id"))

        # 过滤
        new_histories = [h for h in all_histories if h.get("evolution_id") in keep_ids]
        deleted_count = len(all_histories) - len(new_histories)

        if deleted_count > 0:
            # 保存
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(new_histories, f, ensure_ascii=False, indent=2)

            # 删除对应的经验报告
            deleted_ids = set(h.get("evolution_id") for h in all_histories) - keep_ids
            for eid in deleted_ids:
                experience_file = self.experience_dir / f"{eid}.json"
                if experience_file.exists():
                    experience_file.unlink()

            logger.info(f"🧹 自动清理历史: 删除 {deleted_count} 个，保留 {len(new_histories)} 个")

        return deleted_count
    
    def save_best_prompts(self, versions: List[PromptVersion], keep_top_n: int = 5) -> None:
        """保存最佳提示词（只保留前N个）"""
        # 按得分排序，取前N个
        sorted_versions = sorted(versions, key=lambda v: v.avg_ai_score)[:keep_top_n]
        
        data = [v.to_dict() for v in sorted_versions]
        with open(self.best_prompts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 保存最佳提示词: {len(sorted_versions)} 个")
    
    def load_best_prompts(self) -> List[PromptVersion]:
        """加载最佳提示词"""
        if not self.best_prompts_file.exists():
            return []
        
        with open(self.best_prompts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return [PromptVersion.from_dict(d) for d in data]
    
    def approve_prompt(self, version_id: str, evolution_id: str) -> bool:
        """批准提示词"""
        history = self.load_evolution_history(evolution_id)
        if not history:
            return False
        
        # 查找版本
        approved_version = None
        for v in history.best_versions:
            if v.version_id == version_id:
                approved_version = v
                break
        
        if not approved_version:
            return False
        
        # 更新状态
        history.approval_status = ApprovalStatus.APPROVED
        history.approved_version_id = version_id
        self.save_evolution_history(history)
        
        # 保存到已批准提示词文件
        approved_data = {
            "version_id": version_id,
            "evolution_id": evolution_id,
            "prompt_text": approved_version.prompt_text,
            "avg_ai_score": approved_version.avg_ai_score,
            "approved_at": datetime.now().isoformat(),
            "status": "approved"
        }
        
        approved_list = self._load_approved_prompts()
        approved_list.append(approved_data)
        
        with open(self.approved_prompts_file, "w", encoding="utf-8") as f:
            json.dump(approved_list, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ 批准提示词: {version_id}")
        return True
    
    def get_latest_approved_prompt(self) -> Optional[Dict[str, Any]]:
        """获取最新批准的提示词"""
        approved_list = self._load_approved_prompts()
        if not approved_list:
            return None
        return approved_list[-1]

    def save_experience_report(self, evolution_id: str, report: Dict) -> None:
        """保存经验报告"""
        report_file = self.experience_dir / f"{evolution_id}_experience.json"

        report_data = {
            "evolution_id": evolution_id,
            "created_at": datetime.now().isoformat(),
            "effective_strategies": report.get("effective_strategies", []),
            "ineffective_strategies": report.get("ineffective_strategies", []),
            "forbidden_patterns": report.get("forbidden_patterns", []),
            "best_practices": report.get("best_practices", [])
        }

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        logger.info(f"📚 保存经验报告: {evolution_id}")

    def load_experience_report(self, evolution_id: str) -> Optional[Dict]:
        """加载经验报告"""
        report_file = self.experience_dir / f"{evolution_id}_experience.json"
        if not report_file.exists():
            return None

        with open(report_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_all_experience_reports(self) -> List[Dict]:
        """获取所有经验报告"""
        reports = []
        for file in self.experience_dir.glob("*_experience.json"):
            with open(file, "r", encoding="utf-8") as f:
                reports.append(json.load(f))
        return sorted(reports, key=lambda x: x.get("created_at", ""), reverse=True)
    
    def _load_all_histories(self) -> List[Dict]:
        """加载所有历史记录"""
        if not self.history_file.exists():
            return []
        with open(self.history_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _load_approved_prompts(self) -> List[Dict]:
        """加载已批准提示词列表"""
        if not self.approved_prompts_file.exists():
            return []
        with open(self.approved_prompts_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _history_to_dict(self, history: EvolutionHistory) -> Dict:
        """将历史对象转换为字典"""
        return {
            "evolution_id": history.evolution_id,
            "target_score": history.target_score,
            "max_iterations": history.max_iterations,
            "current_iteration": history.current_iteration,
            "status": history.status,
            "best_versions": [v.to_dict() for v in history.best_versions],
            "approval_status": history.approval_status.value,
            "approved_version_id": history.approved_version_id,
            "started_at": history.started_at,
            "completed_at": history.completed_at,
            "error_message": history.error_message
        }
    
    def _dict_to_history(self, data: Dict) -> EvolutionHistory:
        """从字典创建历史对象"""
        return EvolutionHistory(
            evolution_id=data["evolution_id"],
            target_score=data.get("target_score", 30),
            max_iterations=data.get("max_iterations", 10),
            current_iteration=data.get("current_iteration", 0),
            status=data.get("status", "running"),
            best_versions=[PromptVersion.from_dict(v) for v in data.get("best_versions", [])],
            approval_status=ApprovalStatus(data.get("approval_status", "pending")),
            approved_version_id=data.get("approved_version_id"),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message")
        )


# 全局存储实例
_storage: Optional[EvolutionStorage] = None


def get_evolution_storage() -> EvolutionStorage:
    """获取存储管理器单例"""
    global _storage
    if _storage is None:
        _storage = EvolutionStorage()
    return _storage

