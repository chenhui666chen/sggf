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
    # 🔧 段落三分类占比（0-1），2026-10-08 真实网关实测口径：
    # ai_score ≈ (ai_ratio + suspect_ratio) × 100，只在出现「人工」段落时才下降，
    # 对 LLM 改写区间（AI→疑似）恒为 100、无分辨力。故优化目标取 rewritten_ai_ratio。
    rewritten_ai_ratio: Optional[float] = None       # 改写后被判「确定AI」的段落占比
    rewritten_suspect_ratio: Optional[float] = None  # 改写后被判「疑似AI」的段落占比
    rewritten_human_ratio: Optional[float] = None    # 改写后被判「人工」的段落占比
    # 🔧 2026-10-16 段落级真值（[{text,label,conf,start}]，label 0人工/1确定AI/2疑似）。
    # 原先只有三档占比，检测器「到底判了哪几段」这一信息完全丢失，
    # 优化器无法从占比数字反推系统性句式模式（见 meta_optimizer._build_segment_insight）。
    # 只存最小字段，不落供应商原始响应。
    rewritten_segments: List[Dict[str, Any]] = field(default_factory=list)
    # 🔧 2026-10-16 失败语义（受控词表，见 engine.FAILURE_KINDS）。原先只有
    # error 自由文本，事后无法区分「检测失败」与「未检测」，也无法判断失败的
    # 失败样本是否仍持有实测 ratio——而这直接影响适应度口径是否偏乐观。
    # None 表示成功或未标注。
    failure_kind: Optional[str] = None
    evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PromptVersion:
    """提示词版本"""
    version_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    prompt_text: str = ""                           # 提示词内容
    avg_ai_score: float = 100.0                     # 平均AI得分（诊断用；改写区间恒为 100）
    # 🔧 2026-10-08 新增：改写后被判「确定AI」的段落占比均值（0-1，越低越好）。
    # avg_ai_score 恒为 100 使 best_versions 排序退化为按插入序，本字段才是真实适应度。
    avg_ai_ratio: Optional[float] = None
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
    # 🔧 2026-10-08：语义由「各模型AI分数」改为「各模型确定AI段落占比」
    # {model_id: ratio}（0-1，越低越好）。旧值恒为 100 的常量表，无选型价值。
    multi_model_scores: Optional[Dict[str, float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version_id": self.version_id,
            "prompt_text": self.prompt_text,
            "avg_ai_score": self.avg_ai_score,
            "avg_ai_ratio": self.avg_ai_ratio,
            "avg_score_reduction": self.avg_score_reduction,
            "evaluation_results": [
                {
                    "sample_id": r.sample_id,
                    "original_text": r.original_text[:100] + "..." if len(r.original_text) > 100 else r.original_text,
                    "rewritten_text": r.rewritten_text[:100] + "..." if len(r.rewritten_text) > 100 else r.rewritten_text,
                    # 🔧 篇幅可追溯：文本存档截断为100字，完整长度单独记录，
                    # 便于审计改写缩短问题（此前缩短在数据上完全不可追溯）
                    "original_text_length": len(r.original_text),
                    "rewritten_text_length": len(r.rewritten_text),
                    "original_ai_score": r.original_ai_score,
                    "rewritten_ai_score": r.rewritten_ai_score,
                    # 🔧 2026-10-16 补齐段落三分类占比：原先三个字段都未序列化，
                    # 落盘后 ratio 全丢（运行期有值、读档变 None），
                    # 使重启后的续跑退化为无信号。avg_ai_ratio 在版本层，
                    # 但逐样本 ratio 是 A/B 选优与失败归因的唯一明细来源。
                    "rewritten_ai_ratio": r.rewritten_ai_ratio,
                    "rewritten_suspect_ratio": r.rewritten_suspect_ratio,
                    "rewritten_human_ratio": r.rewritten_human_ratio,
                    # 🔧 2026-10-16 段落级真值：不序列化则重启后段落特征
                    # 归因彻底失效（占比还在，但「判了哪几段」的信息消失）。
                    "rewritten_segments": r.rewritten_segments,
                    # 🔧 2026-10-16 失败语义（.get 兼容旧存档缺字段）
                    "failure_kind": r.failure_kind,
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
                # 🔧 2026-10-16：读回段落三分类占比（.get 兼容旧存档缺字段）
                rewritten_ai_ratio=r.get("rewritten_ai_ratio"),
                rewritten_suspect_ratio=r.get("rewritten_suspect_ratio"),
                rewritten_human_ratio=r.get("rewritten_human_ratio"),
                # 🔧 2026-10-16：读回段落真值（.get 兼容旧存档缺字段）
                rewritten_segments=r.get("rewritten_segments") or [],
                failure_kind=r.get("failure_kind"),
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
            avg_ai_ratio=data.get("avg_ai_ratio"),
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

    # 🔧 2026-10-17(P31) 停止原因落盘。
    # 取证（真实 10 轮存档）：86cff7f7(max=6,实际3)、8260b160(max=5,实际3)、
    # 13aa3353(max=4,实际1) 三轮 status=completed 但迭代数远小于上限，
    # 而 error_message 全为 None —— 无法区分「跑满」与「收敛/震荡/崩坏提前退出」。
    # 根因：StopReason 只经 _notify_progress 发给前端，从不写回 history；
    # score_history（收敛/震荡判定的唯一数据源）同样只在内存里，进程退出即丢。
    # 后果：离线分析无法回答「这轮为什么停」，收敛是优化信号，丢了无法判断
    # 系统在进步还是原地打转。
    # 三者均可选且有默认值 —— 旧存档（缺这些键）必须能正常反序列化。
    stop_reason: Optional[str] = None                  # 人可读的停止原因原文
    stop_type: Optional[str] = None                     # 机器可读：见 StopReason.reason_type
    # 🔧 用 element(default_factory=list) 替代 mutability 写法，兼容性一致
    score_history: List[float] = field(default_factory=list)  # 每轮确定AI占比×100，用于离线复核收敛


@dataclass
class EvolutionConfig:
    """进化配置"""
    target_score: int = 30              # 目标AI得分阈值
    max_iterations: int = 10            # 最大迭代次数
    samples_per_iteration: int = 8      # 每次迭代使用的样本数
    early_stop_threshold: int = 10      # 提前停止阈值
    temperature: float = 0.35           # LLM温度参数（改写是风格转换任务，低温收敛可比评估，防二值分布）
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
    ab_test_sample_count: int = 8         # A/B测试使用的样本数（与 samples_per_iteration 对齐：A/B 是进化方向判定的核心，样本数不足时二值分布方差会淹没信号）
    ab_test_variant_count: int = 3        # A/B测试变体数量（2→3）
    # 🔧 2026-10-16 由 3.0 下调至 0.15，配合 `_ab_rank_score` 改帕累托分层。
    #
    # 取证（真实 8 版本存档回放，非构造样本）：
    # 分层后 score = 失格数(层号) + ratio(0~1) + 人感成本项(<=0.13) + 方差罚分(0/0.5)，
    # 实测 score 区间 1.4574 ~ 4.9295（跨度 3.47）。但这个跨度**几乎全部
    # 来自层号（质量层差）**，层内 ratio 的真实最大差只有 0.53：
    #     L1: 253cd2e3 0.4024 / 8f85098d 0.3053  -> 层内差 0.4256
    #     L3: 5df0af76 0.2540 / 53a36ee1 0.4038 / e1d4192a 0.3120 -> 层内差 0.5318
    #     L4: 8f937f18 0.4097 / 31c84958 0.3507  -> 层内差 0.4143
    # 即 3.0 > 层内最大差 0.53 ⇒ **层内 ratio 差异永远判不出显著**，
    # 阈值实际退化成「质量层差门槛」，违背「ratio 是优化目标」的定位。
    #
    # 真实 A/B 场景也要求更低的阈值：主体是同父版本的改造方向，质量通常接近，
    # 真实轮次原始 4 失格 vs 变体 2 失格（层差 2.0）叠加 ratio 0.42->0.25（0.17）
    # 的总diff 约 2.17，仍 < 3.0 —— 判不出显著。
    #
    # 取 0.15：略低于实测跨版本 ratio 跨度 0.169，使真实整轮收益可判显著；
    # 同时远高于噪声级差异（ratio 差 0.01 远低于此），不会把改写随机性当成果。
    ab_test_min_diff: float = 0.15       # A/B最小显著差异（按帕累托分层后的 score 尺度）

    # 🔧 探索模式配置
    exploration_mode_threshold: int = 5   # 连续多少次无明显改善后进入探索模式
    exploration_temperature: float = 0.5  # 探索模式使用的更高温度（相对主温度上调，避免极端发散）
    
    # 🆕 题材定制化配置
    genre: Optional[str] = None           # 目标题材（玄幻/都市/言情/悬疑等）
    # 🔧 2026-10-16 移除 genre_weight_config：题材权重仅被 _calculate_composite_score
    # 读取，而该函数全仓零调用点 → 权重从未参与任何评分。保留字段会让人误以为
    # 「AI 维度占 30% 权重」已生效。综合分现由 evaluator 的 rewritten_multi_score
    # 直接给出，A/B 选优主项为朱雀确定AI段落占比（见 engine._ab_rank_score）。
    
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
    # 停止类型: success/protection/convergence/oscillation/max_iter
    # 🔧 2026-10-17(P31)：另有两个在引擎里直接写入 history.stop_type、
    # 不经过本类的取值 —— initial_abort（初始评估即全失格，engine.py:1176 附近）
    # 与 exception（进化过程抛异常）。全量取值共 7 种：
    #   success / protection / convergence / oscillation / max_iter
    #   / initial_abort / exception
    # 机器可读白名单见 tests/test_stop_reason_persistence.py::EXPECTED。
    reason_type: str = ""               # 停止类型
    reason_message: str = ""            # 停止原因描述
    should_rollback: bool = False       # 是否需要回滚到之前版本
    rollback_reason: str = ""           # 回滚原因
