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
    llm_review: Optional[Dict[str, Any]] = None              # 独立大模型语义质量评审
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
    # 🔧 新增：综合评分（多维加权）
    avg_composite_score: float = 100.0              # 综合评分（越低越好）
    avg_readability: float = 80.0                   # 平均可读性
    avg_writing: float = 50.0                       # 平均文笔分
    # 🆕 题材定制化
    genre: Optional[str] = None                     # 题材标签（玄幻/都市/言情/悬疑等）
    genre_optimized: bool = False                   # 是否针对特定题材优化
    # 🆕 多模型评估结果
    best_model_id: Optional[str] = None             # 多模型评测中表现最佳的模型ID
    multi_model_scores: Optional[Dict[str, float]] = None  # 各模型AI分数 {model_id: score}
    
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
                    "original_multi_score": r.original_multi_score,
                    "rewritten_multi_score": r.rewritten_multi_score,
                    "llm_review": r.llm_review,
                    "evaluated_at": r.evaluated_at
                }
                for r in self.evaluation_results
            ],
            "iteration": self.iteration,
            "parent_version_id": self.parent_version_id,
            "mutation_strategy": self.mutation_strategy,
            "analysis": self.analysis,
            "created_at": self.created_at,
            # 🔧 新增综合评分字段
            "avg_composite_score": self.avg_composite_score,
            "avg_readability": self.avg_readability,
            "avg_writing": self.avg_writing,
            # 🆕 题材标签
            "genre": self.genre,
            "genre_optimized": self.genre_optimized,
            # 🆕 多模型评估结果
            "best_model_id": self.best_model_id,
            "multi_model_scores": self.multi_model_scores,
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
                original_multi_score=r.get("original_multi_score"),
                rewritten_multi_score=r.get("rewritten_multi_score"),
                llm_review=r.get("llm_review"),
                evaluated_at=r.get("evaluated_at", "")
            )
            for r in data.get("evaluation_results", [])
        ]
        # 🔧 智能回退：如果综合评分是默认值100但AI分数更低，使用AI分数
        ai_score = data.get("avg_ai_score", 100.0)
        saved_composite = data.get("avg_composite_score")
        # 如果没有保存综合评分，或者保存的是默认值100但AI分数更低（且AI分数合理），使用AI分数
        # 🔧 保护条件：AI分数必须在合理范围内（>0 且 <100），才进行回退
        if saved_composite is None or (saved_composite >= 100.0 and ai_score < saved_composite and ai_score > 0):
            composite_score = ai_score
        else:
            composite_score = saved_composite

        return cls(
            version_id=data["version_id"],
            prompt_text=data["prompt_text"],
            avg_ai_score=ai_score,
            avg_score_reduction=data.get("avg_score_reduction", 0.0),
            evaluation_results=eval_results,
            iteration=data.get("iteration", 0),
            parent_version_id=data.get("parent_version_id"),
            mutation_strategy=data.get("mutation_strategy"),
            analysis=data.get("analysis", ""),
            created_at=data.get("created_at", ""),
            # 🔧 使用智能回退的综合评分
            avg_composite_score=composite_score,
            avg_readability=data.get("avg_readability", 80.0),
            avg_writing=data.get("avg_writing", 50.0),
            # 🆕 题材标签
            genre=data.get("genre"),
            genre_optimized=data.get("genre_optimized", False),
            # 🆕 多模型评估结果
            best_model_id=data.get("best_model_id"),
            multi_model_scores=data.get("multi_model_scores"),
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
    genre: Optional[str] = None                         # 本次进化固定题材


@dataclass
class EvolutionConfig:
    """进化配置"""
    target_score: int = 30              # 目标AI得分阈值
    max_iterations: int = 10            # 最大迭代次数
    samples_per_iteration: int = 3      # 每次迭代使用的样本数
    early_stop_threshold: int = 10      # 提前停止阈值
    temperature: float = 0.8            # LLM温度参数
    keep_top_n: int = 5                 # 保留最佳版本数量

    # 🆕 多维停止条件
    min_readability_score: float = 85.0   # 最低可读性阈值（低于此值视为不达标）
    max_writing_score: float = 35.0       # 最大文笔分数阈值（高于此值视为不达标，越低越好）
    min_fidelity_similarity: float = 70.0 # 最低保真相似度阈值（相似度≥此值通过）

    # 🆕 保护性停止阈值
    readability_crash_threshold: float = 50.0   # 可读性崩坏阈值（低于此值强制停止）
    writing_crash_threshold: float = 70.0       # 文笔崩坏阈值（高于此值强制停止）

    # 🆕 收敛停止条件
    convergence_threshold: float = 2.0    # 改善幅度阈值（低于此值视为收敛）
    convergence_count: int = 4            # 🔧 连续多少次改善不足视为收敛（3→4）
    oscillation_count: int = 4            # 🔧 连续多少次震荡视为不稳定（3→4）

    # 🔧 A/B测试配置
    ab_test_interval: int = 2             # A/B测试间隔（每N轮进行一次）
    ab_test_sample_count: int = 4         # A/B测试使用的样本数（2→4）
    ab_test_variant_count: int = 3        # A/B测试变体数量（2→3）
    ab_test_min_diff: float = 3.0         # A/B测试最小显著差异（分数差超过此值才判定胜出）

    # 🔧 探索模式配置
    exploration_mode_threshold: int = 5   # 连续多少次无明显改善后进入探索模式
    exploration_temperature: float = 1.0  # 探索模式使用的更高温度
    
    # 🆕 题材定制化配置
    genre: Optional[str] = None           # 目标题材（玄幻/都市/言情/悬疑等）
    genre_weight_config: Optional[Dict[str, float]] = None  # 题材权重配置 {"ai_score": 0.4, "readability": 0.3, "writing": 0.2, "fidelity": 0.1}
    
    # 🆕 多模型评估配置
    multi_model_eval_interval: int = 3    # 多模型评估间隔（每N轮触发一次，0=仅结束时）
    multi_model_eval_at_end: bool = True  # 进化结束时是否强制触发全模型评测

    # 🆕 审核通过标准（四项都需通过，但权重可调整）
    ai_score_threshold: float = 30.0      # AI分数阈值（≤此值通过）
    readability_threshold: float = 70.0   # 可读性阈值（≤此值通过）
    writing_threshold: float = 45.0       # 文笔阈值（≤此值通过）
    fidelity_threshold: float = 80.0      # 保真度阈值（≥此值通过）


@dataclass
class StopReason:
    """停止原因"""
    should_stop: bool = False           # 是否应该停止
    reason_type: str = ""               # 停止类型: success/protection/convergence/oscillation/max_iter
    reason_message: str = ""            # 停止原因描述
    should_rollback: bool = False       # 是否需要回滚到之前版本
    rollback_reason: str = ""           # 回滚原因
