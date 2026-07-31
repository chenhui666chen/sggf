"""
在线提示词实验持久化模型（设计文档 §6：四张表起步，数据库为权威账本）

- PromptChallenger        挑战者池（§3.1 schema + serving_mode 状态机）
- PromptExperiment        实验任务 + 成对结果 + 异步复评结果（一对一合并一行，§5.2 四段状态机在此推进）
- PromptExperimentBudget  预算账本（含未结算预留成本，幂等扣减、失败释放，§9）
- PromptChampionAssignment 冠军指针历史（带生效区间，每行即审计记录，§8.3）
- PromptChallengerStateTransition 挑战者状态变更审计（人工开闸等管理动作落库，§13 #12）

隐私约束：实验任务行只携带 opaque payload reference（payload_ref），
原文在 PayloadVault（experiment_privacy.py）中加密存储，本模块禁止出现原文列。
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PromptChallenger(Base):
    """挑战者池条目（离线准入后进入，serving_mode 状态机见 experiment_contract.ServingMode）"""

    __tablename__ = "prompt_challengers"
    __table_args__ = (
        UniqueConstraint("challenger_id", name="uq_prompt_challengers_challenger_id"),
        Index("ix_prompt_challengers_genre_mode", "genre", "serving_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenger_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    genre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    strategy_desc: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_family: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_batch: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    offline_gate_passed: Mapped[bool] = mapped_column(nullable=False, default=False)
    offline_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    serving_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="shadow", index=True
    )
    state_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PromptExperiment(Base):
    """实验任务 + 成对结果 + 异步复评（一行一实验，四段可重入状态机在 status 上推进）"""

    __tablename__ = "prompt_experiments"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "challenger_id",
            "evaluation_policy_version",
            name="uq_prompt_experiments_settlement",
        ),
        Index("ix_prompt_experiments_claim", "status", "lease_until"),
        Index("ix_prompt_experiments_stats", "challenger_id", "outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    request_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    challenger_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    genre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # ---- 任务字段（§5.2：DB 任务表 + 租约为状态权威）----
    # status: pending / generating / detecting / light_judging / reviewing / settled / dead
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_ref: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payload_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    # ---- 冻结实验契约（§4：解析一次、两路共享，禁止各自重选）----
    champion_id: Mapped[str] = mapped_column(String(120), nullable=False)
    assignment_bucket: Mapped[int] = mapped_column(Integer, nullable=False)
    serving_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    resolved_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    model_selection_source: Mapped[str] = mapped_column(String(40), nullable=False)
    model_config_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    prompt_version_id: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_parameters_hash: Mapped[str] = mapped_column(String(40), nullable=False)

    # ---- 版本字段（§7.2：版本实质变化开新统计窗口）----
    light_judge_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evaluation_policy_version: Mapped[str] = mapped_column(String(60), nullable=False)
    async_review_prompt_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    async_review_model_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    detector_provider: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    detector_version: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    champion_prompt_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    challenger_prompt_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    model_catalog_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    # ---- 结果字段（§7.1 outcome 六分类，晋升只用 confirmed_win）----
    light_judge_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    returned_variant: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    async_review_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    outcome: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    latency_ms: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 冠军原始 AI 检测分（§11.2 champion_ai_score_rise 信号 3a）：结算落库，供休眠期
    # 在线退化滚动窗口判定；越高越差（AI 味越浓）。历史行为空 → 判定侧按证据不足跳过。
    champion_ai_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PromptExperimentBudget(Base):
    """预算账本（§9：按日 × 维度一行；扣减与任务创建同事务，结算释放预留）"""

    __tablename__ = "prompt_experiment_budgets"
    __table_args__ = (
        UniqueConstraint(
            "budget_date", "scope", "scope_key", name="uq_prompt_experiment_budgets_scope"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # scope: global / genre / challenger / user_freq
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reserved_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calls_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    circuit_open: Mapped[bool] = mapped_column(nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PromptChampionAssignment(Base):
    """冠军指针历史（§8.3：effective_until 为空 = 当前指针；每行即审计记录）"""

    __tablename__ = "prompt_champion_assignments"
    __table_args__ = (
        Index("ix_prompt_champion_assignments_current", "genre", "effective_until"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    genre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    prompt_version_id: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_version_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    operator: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gate_overridden: Mapped[bool] = mapped_column(nullable=False, default=False)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PromptChallengerStateTransition(Base):
    """挑战者 serving_mode 变更审计（管理动作与状态变更同事务落库，日志仅为辅助可观测）"""

    __tablename__ = "prompt_challenger_state_transitions"
    __table_args__ = (
        Index("ix_prompt_challenger_transitions_lookup", "challenger_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenger_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    genre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    from_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    to_mode: Mapped[str] = mapped_column(String(20), nullable=False)

    operator: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
