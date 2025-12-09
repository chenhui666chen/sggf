"""
内容创作进化系统 - 数据模型定义

设计原则：
1. 隐式反馈权重：编辑量35% + 保留率35% + 重生次数30%
2. 变体采样率：5%（每20次生成1次测试）
3. 题材差异化评审
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid


class GenerationStage(str, Enum):
    """生成阶段"""
    CONCEPT = "concept"           # 故事概念
    WORLD_BUILDING = "world"      # 世界观
    CHARACTER = "character"       # 人物设计
    OUTLINE = "outline"           # 情节大纲
    CHAPTER = "chapter"           # 章节内容


class FeedbackStatus(str, Enum):
    """反馈收集状态"""
    PENDING = "pending"           # 等待收集
    PARTIAL = "partial"           # 部分收集
    COMPLETE = "complete"         # 收集完成


@dataclass
class ImplicitFeedback:
    """隐式反馈信号"""
    # 编辑量信号 (权重35%)
    original_length: int = 0              # 原始内容长度
    final_length: int = 0                 # 最终内容长度
    edit_distance: int = 0                # 编辑距离（字符级）
    edit_ratio: float = 0.0               # 编辑比例 (0-1, 越低越好)
    
    # 保留率信号 (权重35%)
    was_deleted: bool = False             # 是否被删除
    check_time: Optional[str] = None      # 检查时间（24h后）
    
    # 重生次数信号 (权重30%)
    regenerate_count: int = 0             # 重新生成次数
    
    # 收集状态
    status: FeedbackStatus = FeedbackStatus.PENDING
    collected_at: Optional[str] = None
    
    def calculate_score(self) -> float:
        """
        计算综合隐式反馈得分 (0-100, 越高越好)
        
        权重分配：
        - 编辑量: 35分（改动越少分数越高）
        - 保留率: 35分（保留=满分）
        - 重生次数: 30分（次数越少分数越高）
        """
        score = 0.0
        
        # 1. 编辑量得分 (35分)
        # edit_ratio=0 → 35分, edit_ratio=0.5 → 0分
        edit_score = max(0, 35 * (1 - self.edit_ratio * 2))
        score += edit_score
        
        # 2. 保留率得分 (35分)
        if not self.was_deleted:
            score += 35
        
        # 3. 重生次数得分 (30分)
        # 0次=30分, 1次=15分, 2次及以上=0分
        if self.regenerate_count == 0:
            score += 30
        elif self.regenerate_count == 1:
            score += 15
        # else: 0分
        
        return score
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_length": self.original_length,
            "final_length": self.final_length,
            "edit_distance": self.edit_distance,
            "edit_ratio": self.edit_ratio,
            "was_deleted": self.was_deleted,
            "check_time": self.check_time,
            "regenerate_count": self.regenerate_count,
            "status": self.status.value,
            "collected_at": self.collected_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImplicitFeedback":
        if not data:
            return cls()
        return cls(
            original_length=data.get("original_length", 0),
            final_length=data.get("final_length", 0),
            edit_distance=data.get("edit_distance", 0),
            edit_ratio=data.get("edit_ratio", 0.0),
            was_deleted=data.get("was_deleted", False),
            check_time=data.get("check_time"),
            regenerate_count=data.get("regenerate_count", 0),
            status=FeedbackStatus(data.get("status", "pending")),
            collected_at=data.get("collected_at"),
        )


@dataclass
class AIQualityScore:
    """AI质量评分（复用现有生成时的评分）"""
    genre_fit: float = 0.0        # 题材适配度 (0-100)
    cool_point: float = 0.0       # 爽点效果 (0-100)
    rhythm: float = 0.0           # 节奏合理性 (0-100)
    consistency: float = 0.0      # 设定一致性 (0-100)
    hook: float = 0.0             # 阅读钩子 (0-100)
    writing: float = 0.0          # 文笔流畅度 (0-100)
    
    def average(self) -> float:
        """计算平均分"""
        scores = [self.genre_fit, self.cool_point, self.rhythm, 
                  self.consistency, self.hook, self.writing]
        return sum(scores) / len(scores) if scores else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "genre_fit": self.genre_fit,
            "cool_point": self.cool_point,
            "rhythm": self.rhythm,
            "consistency": self.consistency,
            "hook": self.hook,
            "writing": self.writing,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AIQualityScore":
        if not data:
            return cls()
        return cls(
            genre_fit=data.get("genre_fit", 0.0),
            cool_point=data.get("cool_point", 0.0),
            rhythm=data.get("rhythm", 0.0),
            consistency=data.get("consistency", 0.0),
            hook=data.get("hook", 0.0),
            writing=data.get("writing", 0.0),
        )


@dataclass
class GenerationRecord:
    """生成记录 - 用于进化反馈收集"""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    
    # 基本信息
    project_id: int = 0
    chapter_id: Optional[int] = None      # 章节ID（如果是章节生成）
    stage: GenerationStage = GenerationStage.CHAPTER
    genre: str = "通用"
    
    # 提示词信息
    prompt_version_id: str = ""           # 使用的提示词版本
    prompt_module: str = ""               # 提示词模块名称
    is_variant: bool = False              # 是否是变体测试
    
    # 生成内容
    generated_content: str = ""           # 生成的内容（摘要，最多500字）
    content_length: int = 0               # 内容长度
    
    # AI质量评分（复用现有评分）
    ai_quality_score: Optional[AIQualityScore] = None
    
    # 隐式反馈（延迟收集）
    implicit_feedback: Optional[ImplicitFeedback] = None
    
    # 时间戳
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def get_final_score(self) -> float:
        """
        获取最终综合评分
        
        如果有AI评分：隐式反馈60% + AI评分40%
        否则：100%隐式反馈
        """
        implicit_score = 0.0
        if self.implicit_feedback:
            implicit_score = self.implicit_feedback.calculate_score()
        
        if self.ai_quality_score:
            ai_score = self.ai_quality_score.average()
            # 双信号一致性加分
            bonus = 0
            if (implicit_score > 70 and ai_score > 70) or \
               (implicit_score < 50 and ai_score < 50):
                bonus = 5
            return implicit_score * 0.6 + ai_score * 0.4 + bonus
        else:
            return implicit_score
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "stage": self.stage.value,
            "genre": self.genre,
            "prompt_version_id": self.prompt_version_id,
            "prompt_module": self.prompt_module,
            "is_variant": self.is_variant,
            "generated_content": self.generated_content[:500] if self.generated_content else "",
            "content_length": self.content_length,
            "ai_quality_score": self.ai_quality_score.to_dict() if self.ai_quality_score else None,
            "implicit_feedback": self.implicit_feedback.to_dict() if self.implicit_feedback else None,
            "generated_at": self.generated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GenerationRecord":
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())[:12]),
            project_id=data.get("project_id", 0),
            chapter_id=data.get("chapter_id"),
            stage=GenerationStage(data.get("stage", "chapter")),
            genre=data.get("genre", "通用"),
            prompt_version_id=data.get("prompt_version_id", ""),
            prompt_module=data.get("prompt_module", ""),
            is_variant=data.get("is_variant", False),
            generated_content=data.get("generated_content", ""),
            content_length=data.get("content_length", 0),
            ai_quality_score=AIQualityScore.from_dict(data.get("ai_quality_score")) if data.get("ai_quality_score") else None,
            implicit_feedback=ImplicitFeedback.from_dict(data.get("implicit_feedback")) if data.get("implicit_feedback") else None,
            generated_at=data.get("generated_at", datetime.now().isoformat()),
        )


@dataclass
class PromptVariant:
    """提示词变体"""
    variant_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # 基础信息
    module_name: str = ""                 # 模块名（如 chapter_prompt, outline_prompt）
    genre: str = "通用"                   # 适用题材
    
    # 内容
    prompt_text: str = ""                 # 提示词内容
    parent_id: Optional[str] = None       # 父版本ID
    mutation_description: str = ""        # 变异描述
    
    # 评估统计
    sample_count: int = 0                 # 样本数量
    avg_score: float = 0.0                # 平均得分
    score_std: float = 0.0                # 得分标准差
    
    # 状态
    is_current_best: bool = False         # 是否是当前最佳
    is_active: bool = True                # 是否激活（用于测试）
    
    # 时间戳
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_evaluated_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "module_name": self.module_name,
            "genre": self.genre,
            "prompt_text": self.prompt_text,
            "parent_id": self.parent_id,
            "mutation_description": self.mutation_description,
            "sample_count": self.sample_count,
            "avg_score": self.avg_score,
            "score_std": self.score_std,
            "is_current_best": self.is_current_best,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_evaluated_at": self.last_evaluated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptVariant":
        return cls(
            variant_id=data.get("variant_id", str(uuid.uuid4())[:8]),
            module_name=data.get("module_name", ""),
            genre=data.get("genre", "通用"),
            prompt_text=data.get("prompt_text", ""),
            parent_id=data.get("parent_id"),
            mutation_description=data.get("mutation_description", ""),
            sample_count=data.get("sample_count", 0),
            avg_score=data.get("avg_score", 0.0),
            score_std=data.get("score_std", 0.0),
            is_current_best=data.get("is_current_best", False),
            is_active=data.get("is_active", True),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_evaluated_at=data.get("last_evaluated_at"),
        )


@dataclass
class EvolutionSession:
    """进化会话 - 记录一次进化周期"""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    
    # 目标
    module_name: str = ""                 # 目标模块
    genre: str = "通用"                   # 目标题材
    
    # 进化状态
    status: str = "running"               # running/completed/paused
    current_best_id: Optional[str] = None # 当前最佳变体ID
    
    # 统计
    total_samples: int = 0                # 总样本数
    variants_tested: int = 0              # 已测试变体数
    improvement_rate: float = 0.0         # 改善率
    
    # 配置
    min_samples_for_evolution: int = 50   # 最少样本数才进化
    variant_ratio: float = 0.05           # 变体测试比例（5%）
    
    # 时间戳
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_evolution_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "module_name": self.module_name,
            "genre": self.genre,
            "status": self.status,
            "current_best_id": self.current_best_id,
            "total_samples": self.total_samples,
            "variants_tested": self.variants_tested,
            "improvement_rate": self.improvement_rate,
            "min_samples_for_evolution": self.min_samples_for_evolution,
            "variant_ratio": self.variant_ratio,
            "started_at": self.started_at,
            "last_evolution_at": self.last_evolution_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvolutionSession":
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())[:12]),
            module_name=data.get("module_name", ""),
            genre=data.get("genre", "通用"),
            status=data.get("status", "running"),
            current_best_id=data.get("current_best_id"),
            total_samples=data.get("total_samples", 0),
            variants_tested=data.get("variants_tested", 0),
            improvement_rate=data.get("improvement_rate", 0.0),
            min_samples_for_evolution=data.get("min_samples_for_evolution", 50),
            variant_ratio=data.get("variant_ratio", 0.05),
            started_at=data.get("started_at", datetime.now().isoformat()),
            last_evolution_at=data.get("last_evolution_at"),
        )


@dataclass
class ContentEvolutionConfig:
    """内容进化配置"""
    # 采样配置
    variant_ratio: float = 0.05           # 变体测试比例（5% = 每20次1次）
    min_samples_for_evolution: int = 50   # 最少样本数才触发进化
    
    # 反馈权重
    edit_weight: float = 0.35             # 编辑量权重
    retention_weight: float = 0.35        # 保留率权重
    regenerate_weight: float = 0.30       # 重生次数权重
    
    # 信号收集
    retention_check_hours: int = 24       # 保留率检查间隔（小时）
    
    # 进化触发条件
    evolution_threshold: float = 5.0      # 变体需比当前最佳高出多少分才提升
    discard_threshold: float = -10.0      # 变体比当前最佳低多少分才丢弃
    score_std_threshold: float = 15.0     # 得分标准差阈值（超过则继续观察）
    
    # AI评分权重（如果有）
    implicit_weight: float = 0.60         # 隐式反馈权重
    ai_score_weight: float = 0.40         # AI评分权重
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_ratio": self.variant_ratio,
            "min_samples_for_evolution": self.min_samples_for_evolution,
            "edit_weight": self.edit_weight,
            "retention_weight": self.retention_weight,
            "regenerate_weight": self.regenerate_weight,
            "retention_check_hours": self.retention_check_hours,
            "evolution_threshold": self.evolution_threshold,
            "discard_threshold": self.discard_threshold,
            "score_std_threshold": self.score_std_threshold,
            "implicit_weight": self.implicit_weight,
            "ai_score_weight": self.ai_score_weight,
        }
