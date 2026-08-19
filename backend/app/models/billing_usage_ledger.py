"""计费用量账本与人工对账审计模型（GUIDE §1.1：R9/P1-3、R11/P1-2 四态、R16/P2-1、R17/P1-1）"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.db.base import Base


class BillingUsageLedger(Base):
    """用量事实源（R9/P1-3；R10 状态机；R11 四态 pending/succeeded/confirmed_failed/manual_reconciliation）"""

    __tablename__ = "billing_usage_ledger"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, server_default="pending")
    # 内部幂等键（对齐 provider_recovery.internal_attempt_key：generation_input_hash:attempt_number）
    attempt_key = Column(String(64), nullable=False)
    provider = Column(String(32), nullable=False)  # seed_provider | asr_provider | fallback_tts ...
    # 用量维度键（R18/P1-3）：pending 时未知可空，succeeded 时必须非空（R17/P1-4 CHECK）
    pricing_key = Column(String(64), nullable=True)
    provider_request_id = Column(String(64), nullable=True)  # 供应商原始请求 ID（R13/P0-b）
    encrypted_result_url = Column(Text, nullable=True)
    result_url_expires_at = Column(DateTime(timezone=True), nullable=True)
    usage_kind = Column(String(32), nullable=False)  # seed_render | tts_chars | asr_seconds | remix
    quantity = Column(Numeric(20, 6), nullable=True)  # pending 时未知为空，succeeded 时必须 > 0
    unit = Column(String(16), nullable=False)  # second | char（与 billing_snapshot.prices[*].unit 同值域）
    billing_snapshot_id = Column(String(64), nullable=True)  # succeeded 时必须非空（R17/P1-4 CHECK）
    idempotency_key_sent = Column(Boolean, nullable=False, server_default="false")  # R12/P1-3
    recovery_method = Column(String(32), nullable=True)  # request_query | temporary_url | replay | manual
    result_url_persisted_at = Column(DateTime(timezone=True), nullable=True)
    capability_snapshot_json = Column(JSON, nullable=True)  # 调用时能力完整快照（R13/P0-b）
    commit_stage = Column(String(16), nullable=False, server_default="pre_call")  # R12/P1-3
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # 内部去重：同 run 同 attempt_key 只记一条（调用前写 pending，重试幂等）
        UniqueConstraint("run_id", "attempt_key", name="uq_billing_usage_ledger_attempt"),
        # 供应商侧去重：provider_request_id 可空，NULL 不参与去重（R11/P1-2 部分唯一索引；R14/P0）
        Index(
            "uq_billing_usage_ledger_dedup",
            "run_id",
            "provider",
            "provider_request_id",
            "usage_kind",
            unique=True,
            postgresql_where=text("provider_request_id IS NOT NULL"),
        ),
        CheckConstraint(
            "status IN ('pending','succeeded','confirmed_failed','manual_reconciliation')",
            name="ck_billing_usage_ledger_status",
        ),
        CheckConstraint(
            "usage_kind IN ('seed_render','tts_chars','asr_seconds','remix')",
            name="ck_billing_usage_ledger_usage_kind",
        ),
        # succeeded 必须可结算：实际用量 + 有效计价键 + 有效快照引用（R16/P0、R17/P1-4）
        CheckConstraint(
            "status <> 'succeeded' OR (quantity IS NOT NULL AND quantity > 0 "
            "AND pricing_key IS NOT NULL AND billing_snapshot_id IS NOT NULL)",
            name="ck_billing_usage_ledger_succeeded_fields",
        ),
        # 计量单位值域（R17/P1-4；R19/P1-1 唯一单位常量表）
        CheckConstraint("unit IN ('second','char')", name="ck_billing_usage_ledger_unit"),
        # 提交阶段值域（R12/P1-3）
        CheckConstraint(
            "commit_stage IN ('pre_call','post_call','result_persisted')",
            name="ck_billing_usage_ledger_commit_stage",
        ),
    )


class LedgerReconciliationAudit(Base):
    """人工对账转态的唯一审计落点（R15/P1-4；R16/P2-1 完整约束模型，append-only）"""

    __tablename__ = "ledger_reconciliation_audits"

    id = Column(Integer, primary_key=True)  # 显式主键（R16/P2-1）
    # RESTRICT 防 ledger 删除后审计悬空（R16/P2-1）
    ledger_id = Column(
        Integer, ForeignKey("billing_usage_ledger.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_status = Column(String(32), nullable=False, server_default="manual_reconciliation")
    to_status = Column(String(32), nullable=False)  # succeeded | confirmed_failed
    operator_user_id = Column(Integer, nullable=False)
    operator_username = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    evidence = Column(JSON, nullable=False)  # 自由结构只存原始回执，证据事实以结构化字段为准（R17/P1-1）
    # 人工确认的用量事实快照（R16/P0：succeeded 必填且 > 0；confirmed_failed 为 NULL）
    confirmed_quantity = Column(Numeric(20, 6), nullable=True)
    previous_provider_request_id = Column(String(64), nullable=True)
    new_provider_request_id = Column(String(64), nullable=True)  # 仅 NULL 补齐，已有值时不变
    previous_commit_stage = Column(String(16), nullable=True)  # pre_call|post_call|result_persisted
    new_commit_stage = Column(String(16), nullable=True)  # 单调推进，禁止 result_persisted 倒退
    recovery_method = Column(String(16), nullable=False, server_default="manual")
    reconciled_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "from_status = 'manual_reconciliation'", name="ck_ledger_reconciliation_audits_from"
        ),
        CheckConstraint(
            "to_status IN ('succeeded','confirmed_failed')", name="ck_ledger_reconciliation_audits_to"
        ),
        # 用量事实一致性（R16/P0）
        CheckConstraint(
            "to_status <> 'succeeded' OR (confirmed_quantity IS NOT NULL AND confirmed_quantity > 0)",
            name="ck_ledger_reconciliation_audits_quantity",
        ),
        CheckConstraint(
            "to_status <> 'confirmed_failed' OR confirmed_quantity IS NULL",
            name="ck_ledger_reconciliation_audits_quantity_null",
        ),
        # 结构化证据值域（R17/P1-1）
        CheckConstraint(
            "previous_commit_stage IS NULL OR previous_commit_stage IN ('pre_call','post_call','result_persisted')",
            name="ck_ledger_reconciliation_audits_prev_stage",
        ),
        CheckConstraint(
            "new_commit_stage IS NULL OR new_commit_stage IN ('pre_call','post_call','result_persisted')",
            name="ck_ledger_reconciliation_audits_new_stage",
        ),
        # 单调性 rank 编码 pre_call=1 < post_call=2 < result_persisted=3，new ≥ prev（R18/P1-1）
        CheckConstraint(
            "to_status <> 'succeeded' OR (new_commit_stage IS NOT NULL AND previous_commit_stage IS NOT NULL "
            "AND CASE new_commit_stage WHEN 'pre_call' THEN 1 WHEN 'post_call' THEN 2 ELSE 3 END "
            ">= CASE previous_commit_stage WHEN 'pre_call' THEN 1 WHEN 'post_call' THEN 2 ELSE 3 END)",
            name="ck_ledger_reconciliation_audits_stage_monotonic",
        ),
        CheckConstraint(
            "recovery_method IN ('manual')", name="ck_ledger_reconciliation_audits_recovery"
        ),
    )
