"""
提示词进化系统 - 数据模型定义
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid


class ApprovalStatus(str, Enum):
    """审批状态"""
    PENDING = "pending"         # 待审核
    APPROVED = "approved"       # 已批准
    REJECTED = "rejected"       # 已拒绝
    APPLIED = "applied"         # 已应用到生产


@dataclass
class AITraceDetail:
    """AI痕迹详细信息"""
    hit_keywords: List[str] = field(default_factory=list)      # 命中的关键词
    hit_positions: List[Dict] = field(default_factory=list)    # 命中位置
    detection_method: str = ""                                  # 检测方法
    label_scores: Dict[str, int] = field(default_factory=dict)  # 各标签得分
    problematic_segments: List[Dict] = field(default_factory=list)  # 问题片段

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hit_keywords": self.hit_keywords,
            "hit_positions": self.hit_positions,
            "detection_method": self.detection_method,
            "label_scores": self.label_scores,
            "problematic_segments": self.problematic_segments
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AITraceDetail":
        if not data:
            return cls()
        return cls(
            hit_keywords=data.get("hit_keywords", []),
            hit_positions=data.get("hit_positions", []),
            detection_method=data.get("detection_method", ""),
            label_scores=data.get("label_scores", {}),
            problematic_segments=data.get("problematic_segments", [])
        )


@dataclass
class EvaluationResult:
    """单次评估结果"""
    sample_id: str                      # 测试样本ID
    original_text: str                  # 原始文本
    rewritten_text: str                 # 改写后文本
    original_ai_score: Optional[int]    # 原始AI得分
    rewritten_ai_score: Optional[int]   # 改写后AI得分
    score_reduction: int                # 得分下降值
    success: bool                       # 是否成功
    error: Optional[str] = None         # 错误信息
    # 🆕 AI痕迹详细信息
    original_trace_detail: Optional[AITraceDetail] = None   # 原始文本的AI痕迹详情
    rewritten_trace_detail: Optional[AITraceDetail] = None  # 改写后的AI痕迹详情
    # 🆕 量化指标
    original_metrics: Optional[Dict[str, Any]] = None       # 原始文本量化指标
    rewritten_metrics: Optional[Dict[str, Any]] = None      # 改写后量化指标
    metrics_comparison: Optional[str] = None                 # 指标对比摘要
    # 🆕 多维评分
    original_multi_score: Optional[Dict[str, Any]] = None   # 原始文本多维评分
    rewritten_multi_score: Optional[Dict[str, Any]] = None  # 改写后多维评分
    evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PromptVersion:
    """提示词版本"""
    version_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    prompt_text: str = ""                           # 提示词内容
    avg_ai_score: float = 100.0                     # 平均AI得分
    avg_score_reduction: float = 0.0                # 平均得分下降
    evaluation_results: List[EvaluationResult] = field(default_factory=list)
    iteration: int = 0                              # 迭代次数
    parent_version_id: Optional[str] = None         # 父版本ID
    mutation_strategy: Optional[str] = None         # 使用的变异策略
    analysis: str = ""                              # 优化分析
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version_id": self.version_id,
            "prompt_text": self.prompt_text,
            "avg_ai_score": self.avg_ai_score,
            "avg_score_reduction": self.avg_score_reduction,
            "evaluation_results": [
                {
                    "sample_id": r.sample_id,
                    "original_text": r.original_text[:100] + "..." if len(r.original_text) > 100 else r.original_text,
                    "rewritten_text": r.rewritten_text[:100] + "..." if len(r.rewritten_text) > 100 else r.rewritten_text,
                    "original_ai_score": r.original_ai_score,
                    "rewritten_ai_score": r.rewritten_ai_score,
                    "score_reduction": r.score_reduction,
                    "success": r.success,
                    "error": r.error,
                    # AI痕迹详情
                    "original_trace_detail": r.original_trace_detail.to_dict() if r.original_trace_detail else None,
                    "rewritten_trace_detail": r.rewritten_trace_detail.to_dict() if r.rewritten_trace_detail else None,
                    # 🆕 量化指标
                    "original_metrics": r.original_metrics,
                    "rewritten_metrics": r.rewritten_metrics,
                    "metrics_comparison": r.metrics_comparison,
                    "evaluated_at": r.evaluated_at
                }
                for r in self.evaluation_results
            ],
            "iteration": self.iteration,
            "parent_version_id": self.parent_version_id,
            "mutation_strategy": self.mutation_strategy,
            "analysis": self.analysis,
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptVersion":
        """从字典创建"""
        eval_results = [
            EvaluationResult(
                sample_id=r["sample_id"],
                original_text=r["original_text"],
                rewritten_text=r["rewritten_text"],
                original_ai_score=r["original_ai_score"],
                rewritten_ai_score=r["rewritten_ai_score"],
                score_reduction=r["score_reduction"],
                success=r["success"],
                error=r.get("error"),
                # AI痕迹详情
                original_trace_detail=AITraceDetail.from_dict(r.get("original_trace_detail")) if r.get("original_trace_detail") else None,
                rewritten_trace_detail=AITraceDetail.from_dict(r.get("rewritten_trace_detail")) if r.get("rewritten_trace_detail") else None,
                # 量化指标
                original_metrics=r.get("original_metrics"),
                rewritten_metrics=r.get("rewritten_metrics"),
                metrics_comparison=r.get("metrics_comparison"),
                evaluated_at=r.get("evaluated_at", "")
            )
            for r in data.get("evaluation_results", [])
        ]
        return cls(
            version_id=data["version_id"],
            prompt_text=data["prompt_text"],
            avg_ai_score=data.get("avg_ai_score", 100.0),
            avg_score_reduction=data.get("avg_score_reduction", 0.0),
            evaluation_results=eval_results,
            iteration=data.get("iteration", 0),
            parent_version_id=data.get("parent_version_id"),
            mutation_strategy=data.get("mutation_strategy"),
            analysis=data.get("analysis", ""),
            created_at=data.get("created_at", "")
        )


@dataclass
class EvolutionHistory:
    """进化历史记录"""
    evolution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    target_score: int = 30                          # 目标AI得分
    max_iterations: int = 10                        # 最大迭代次数
    current_iteration: int = 0                      # 当前迭代
    status: str = "running"                         # running/completed/failed
    best_versions: List[PromptVersion] = field(default_factory=list)  # 最佳版本(保留前5)
    all_versions: List[PromptVersion] = field(default_factory=list)   # 所有版本
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approved_version_id: Optional[str] = None       # 被批准的版本ID
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


@dataclass  
class EvolutionConfig:
    """进化配置"""
    target_score: int = 30              # 目标AI得分阈值
    max_iterations: int = 10            # 最大迭代次数
    samples_per_iteration: int = 3      # 每次迭代使用的样本数
    early_stop_threshold: int = 25      # 提前停止阈值
    temperature: float = 0.8            # LLM温度参数
    keep_top_n: int = 5                 # 保留最佳版本数量

